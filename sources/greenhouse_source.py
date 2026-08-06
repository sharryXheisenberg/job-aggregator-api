"""
sources/greenhouse_source.py

Greenhouse's public job-board JSON API -- documented, sanctioned for
exactly this kind of embed/aggregation use, no auth required:
    https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true

Company-scoped: only fetches for TrackedCompany rows where
source == "greenhouse" and active is True.
"""

from __future__ import annotations
import logging
import requests

from sources.base import JobSource, CanonicalJob

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


class GreenhouseSource(JobSource):
    source_name = "greenhouse"

    def fetch(self, tracked_companies: list) -> list[CanonicalJob]:
        jobs: list[CanonicalJob] = []
        companies = [
            c for c in tracked_companies
            if c.source == self.source_name and c.active
        ]

        for company in companies:
            url = BASE_URL.format(slug=company.company_slug)
            try:
                resp = requests.get(url, params={"content": "true"}, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                # One bad/renamed company board must never take down the
                # whole Greenhouse fetch for every other tracked company.
                logger.warning("Greenhouse fetch failed for %s: %s", company.company_slug, exc)
                continue

            for posting in data.get("jobs", []):
                location_name = (posting.get("location") or {}).get("name", "") or ""
                title = (posting.get("title") or "").strip()
                jobs.append(CanonicalJob(
                    title=title,
                    company=company.display_name,
                    location=location_name or None,
                    remote="remote" in (title + " " + location_name).lower(),
                    salary_min=None,
                    salary_max=None,
                    description=posting.get("content") or "",
                    apply_url=posting.get("absolute_url") or "",
                    source=self.source_name,
                    posted_date=(posting.get("updated_at") or "")[:10] or None,
                    tags=[d["name"] for d in posting.get("departments", []) if d.get("name")],
                ))

        return jobs
