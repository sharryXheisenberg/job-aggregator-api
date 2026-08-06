"""
sources/remoteok_source.py

RemoteOK's public JSON feed -- a full aggregate feed, not scoped to any
particular company:
    https://remoteok.com/api

Feed-based: ignores `tracked_companies` entirely (there's no per-company
slug to look up -- this endpoint just returns everything RemoteOK has).

Note: RemoteOK's response has a quirk -- the FIRST element of the JSON
array is a metadata/legal-notice object, not a job posting. We skip
anything that doesn't look like an actual posting (missing an "id" field).
"""

from __future__ import annotations
import logging
import requests

from sources.base import JobSource, CanonicalJob

logger = logging.getLogger(__name__)

FEED_URL = "https://remoteok.com/api"


class RemoteOKSource(JobSource):
    source_name = "remoteok"

    def fetch(self, tracked_companies: list) -> list[CanonicalJob]:
        jobs: list[CanonicalJob] = []
        # No try/except here on purpose: a feed-based source has no
        # per-item granularity like Greenhouse/Lever's per-company loop.
        # A network/parsing failure here means the WHOLE source is down
        # right now, which is exactly what refresh.py's per-source
        # try/except is meant to catch and record in sources_failed --
        # swallowing it here would make "feed unreachable" look identical
        # to "feed genuinely had zero postings today".
        resp = requests.get(
            FEED_URL,
            timeout=15,
            headers={"User-Agent": "jobs-aggregator-api (contact: you@example.com)"},
        )
        resp.raise_for_status()
        data = resp.json()

        for posting in data:
            if not isinstance(posting, dict) or "id" not in posting:
                continue  # the metadata/legal-notice element, not a job

            jobs.append(CanonicalJob(
                title=(posting.get("position") or "").strip(),
                company=(posting.get("company") or "").strip(),
                location=posting.get("location") or "Remote",
                remote=True,
                salary_min=self._safe_float(posting.get("salary_min")),
                salary_max=self._safe_float(posting.get("salary_max")),
                description=posting.get("description") or "",
                apply_url=posting.get("url") or "",
                source=self.source_name,
                posted_date=(posting.get("date") or "")[:10] or None,
                tags=posting.get("tags") or [],
            ))

        return jobs

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
