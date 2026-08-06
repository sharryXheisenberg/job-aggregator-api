"""
sources/base.py

The contract every job source must implement -- same pattern as
parsers/base.py in the bank statement parser project, applied here.

Liskov Substitution Principle: refresh.py calls every registered source
exactly the same way -- `source.fetch(tracked_companies)` -- and gets back
a `list[CanonicalJob]` every time, regardless of whether the source is:
  - company-scoped (Greenhouse, Lever: only returns jobs for companies in
    `tracked_companies` whose `source` field matches this source's name;
    ignores everything else in the list)
  - feed-based (RemoteOK, Remotive: returns its entire public feed and
    ignores `tracked_companies` completely)
refresh.py never needs an if/else per source type to know which kind it's
calling -- every source is a drop-in substitute for another.

Open/Closed Principle: adding a 5th source (once you find one with a real
public/sanctioned endpoint) means writing one new file here and nothing
else -- see sources/__init__.py's auto-discovery.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CanonicalJob:
    """
    The one schema every source normalizes to, regardless of how wildly
    different each source's raw JSON looks. This is what makes the API's
    output consistent no matter which source a posting came from -- the
    same substitutability guarantee CANONICAL_COLUMNS gave the bank parser.
    """
    title: str
    company: str
    location: Optional[str]
    remote: bool
    salary_min: Optional[float]
    salary_max: Optional[float]
    description: str
    apply_url: str
    source: str
    posted_date: Optional[str]  # ISO YYYY-MM-DD string, or None if unknown
    tags: list[str] = field(default_factory=list)


class JobSource(ABC):
    """Abstract base every job source subclasses."""

    source_name: str = "UNSET"

    @abstractmethod
    def fetch(self, tracked_companies: list) -> list[CanonicalJob]:
        """
        Return every job posting this source currently has available.

        `tracked_companies` is the FULL list of TrackedCompany rows across
        every source -- not pre-filtered. Company-scoped sources must filter
        it down to rows where `company.source == self.source_name` and
        `company.active` is True. Feed-based sources can ignore the
        argument entirely.

        Must never raise for "this one company's board 404'd" or "this feed
        was temporarily empty" -- log/skip internally and return whatever
        WAS successfully fetched. Only raise for something that means the
        whole source is unreachable (network down, credentials broken),
        since refresh.py catches source-level exceptions and skips that
        source for this cycle rather than aborting the whole refresh.
        """
        raise NotImplementedError
