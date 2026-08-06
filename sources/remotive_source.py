"""
sources/remotive_source.py

Remotive's public JSON feed -- documented, free, no auth required:
    https://remotive.com/api/remote-jobs

Feed-based: ignores `tracked_companies` entirely, same as RemoteOK.
"""

from __future__ import annotations
import logging
import requests

from sources.base import JobSource, CanonicalJob

logger = logging.getLogger(__name__)

FEED_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    source_name = "remotive"

    def fetch(self, tracked_companies: list) -> list[CanonicalJob]:
        jobs: list[CanonicalJob] = []
        # See RemoteOKSource for why this deliberately doesn't catch
        # network/parsing exceptions -- feed-based sources have no finer
        # granularity than "the whole source", so a failure here should
        # propagate to refresh.py's sources_failed tracking.
        resp = requests.get(FEED_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for posting in data.get("jobs", []):
            jobs.append(CanonicalJob(
                title=(posting.get("title") or "").strip(),
                company=(posting.get("company_name") or "").strip(),
                location=posting.get("candidate_required_location") or "Remote",
                remote=True,
                salary_min=None,
                salary_max=None,
                description=posting.get("description") or "",
                apply_url=posting.get("url") or "",
                source=self.source_name,
                posted_date=(posting.get("publication_date") or "")[:10] or None,
                tags=posting.get("tags") or [],
            ))

        return jobs
