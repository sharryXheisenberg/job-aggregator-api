"""
sources/lever_source.py

Lever's public postings JSON API -- documented, sanctioned for embedding
job boards, no auth required:
    https://api.lever.co/v0/postings/{company_slug}?mode=json

Company-scoped: only fetches for TrackedCompany rows where
source == "lever" and active is True.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
import requests

from sources.base import JobSource, CanonicalJob

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{slug}"


class LeverSource(JobSource):
    source_name = "lever"

    def fetch(self, tracked_companies: list) -> list[CanonicalJob]:
        jobs: list[CanonicalJob] = []
        companies = [
            c for c in tracked_companies
            if c.source == self.source_name and c.active
        ]

        for company in companies:
            url = BASE_URL.format(slug=company.company_slug)
            try:
                resp = requests.get(url, params={"mode": "json"}, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("Lever fetch failed for %s: %s", company.company_slug, exc)
                continue

            for posting in data:
                categories = posting.get("categories") or {}
                location = categories.get("location") or ""
                title = (posting.get("text") or "").strip()

                posted_date = None
                created_at = posting.get("createdAt")
                if created_at:
                    try:
                        posted_date = datetime.fromtimestamp(
                            created_at / 1000, tz=timezone.utc
                        ).date().isoformat()
                    except (TypeError, ValueError, OverflowError):
                        posted_date = None

                jobs.append(CanonicalJob(
                    title=title,
                    company=company.display_name,
                    location=location or None,
                    remote="remote" in location.lower(),
                    salary_min=None,
                    salary_max=None,
                    description=posting.get("descriptionPlain") or posting.get("description") or "",
                    apply_url=posting.get("hostedUrl") or "",
                    source=self.source_name,
                    posted_date=posted_date,
                    tags=[categories["team"]] if categories.get("team") else [],
                ))

        return jobs
