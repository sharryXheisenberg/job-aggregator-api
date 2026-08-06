"""
models.py

Two tables:

  tracked_companies -- the "expandable list" for company-scoped sources
  (Greenhouse, Lever). Adding a company is one row via scripts/add_company.py
  -- zero code changes, zero redeploy. Feed-based sources (RemoteOK,
  Remotive) never read this table at all.

  jobs -- the actual cached postings every API request serves from.
  Never fetched live per-request; only refresh.py writes to it.

Note on `tags`: stored as a comma-separated string rather than a JSON/array
column. This is a deliberate portability choice -- SQLite (used for local
dev) and Postgres (used in production) don't share JSON-query semantics,
and a plain string + ILIKE keeps filtering logic identical on both without
dialect-specific code.
"""

from __future__ import annotations
import datetime
from sqlalchemy import Column, String, Boolean, Float, Text, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TrackedCompany(Base):
    __tablename__ = "tracked_companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)         # "greenhouse" | "lever"
    company_slug = Column(String(255), nullable=False)  # the board's URL slug
    display_name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    added_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "company_slug", name="uq_source_company_slug"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)  # dedup hash, see refresh.py
    title = Column(String(500), nullable=False)
    company = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    remote = Column(Boolean, default=False, nullable=False)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    apply_url = Column(Text, nullable=False)
    source = Column(String(50), nullable=False)
    posted_date = Column(String(10), nullable=True)  # ISO YYYY-MM-DD
    tags = Column(Text, nullable=True)               # comma-separated, see note above
    first_seen_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
