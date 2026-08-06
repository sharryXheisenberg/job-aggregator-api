"""
refresh.py

The script GitHub Actions runs on a schedule (see .github/workflows/refresh.yml).
Pulls from every registered JobSource, dedups against what's already stored,
and upserts into the database main.py reads from.

Dedup strategy: a job's identity is (source, apply_url) if apply_url is
present, else (source, title, company) as a fallback for postings that
somehow lack a URL. Hashed into a short id. Re-fetching the same posting
across refresh cycles just bumps last_seen_at rather than creating a
duplicate row -- this is also what will eventually let the API expose a
genuine "freshness" signal (how long a posting has been live) rather than
just a static posted_date.

Run manually with:
    python refresh.py
"""

from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timezone

from db import SessionLocal, init_db
from models import Job, TrackedCompany
from sources import SOURCE_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh")


def make_job_id(source: str, apply_url: str, title: str, company: str) -> str:
    key_parts = [source.lower().strip()]
    if apply_url:
        key_parts.append(apply_url.lower().strip())
    else:
        key_parts.extend([title.lower().strip(), company.lower().strip()])
    key = "|".join(key_parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def run_refresh() -> dict:
    init_db()
    session = SessionLocal()
    stats = {"new": 0, "updated": 0, "sources_failed": []}

    try:
        tracked_companies = session.query(TrackedCompany).filter_by(active=True).all()
        now = datetime.now(timezone.utc)

        for source_name, source_cls in SOURCE_REGISTRY.items():
            source = source_cls()
            try:
                canonical_jobs = source.fetch(tracked_companies)
            except Exception as exc:
                # A source being entirely unreachable must not kill the
                # refresh for every other source.
                logger.error("Source '%s' failed entirely, skipping: %s", source_name, exc)
                stats["sources_failed"].append(source_name)
                continue

            logger.info("Source '%s' returned %d postings", source_name, len(canonical_jobs))

            for cj in canonical_jobs:
                job_id = make_job_id(cj.source, cj.apply_url, cj.title, cj.company)
                existing = session.get(Job, job_id)

                if existing:
                    existing.last_seen_at = now
                    # Description/salary can legitimately change between
                    # refreshes (a posting gets edited) -- keep them fresh.
                    existing.description = cj.description
                    existing.salary_min = cj.salary_min
                    existing.salary_max = cj.salary_max
                    stats["updated"] += 1
                else:
                    session.add(Job(
                        id=job_id,
                        title=cj.title,
                        company=cj.company,
                        location=cj.location,
                        remote=cj.remote,
                        salary_min=cj.salary_min,
                        salary_max=cj.salary_max,
                        description=cj.description,
                        apply_url=cj.apply_url,
                        source=cj.source,
                        posted_date=cj.posted_date,
                        tags=",".join(cj.tags) if cj.tags else "",
                        first_seen_at=now,
                        last_seen_at=now,
                    ))
                    stats["new"] += 1

        session.commit()
        logger.info(
            "Refresh complete: %d new, %d updated, sources failed: %s",
            stats["new"], stats["updated"], stats["sources_failed"] or "none",
        )
        return stats
    finally:
        session.close()


if __name__ == "__main__":
    run_refresh()
