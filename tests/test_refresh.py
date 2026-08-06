"""
tests/test_refresh.py

Tests refresh.py's actual dedup/upsert logic end-to-end against a real
database (whatever DATABASE_URL is set to when running these tests --
in CI this should be pointed at Postgres, same as production, not just
SQLite, to catch anything Postgres-specific).
"""

import os
import responses

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_refresh.db")

from db import SessionLocal, init_db, engine  # noqa: E402
from models import Base, Job, TrackedCompany  # noqa: E402
import refresh  # noqa: E402


def setup_function():
    # Clean slate for every test -- drop and recreate tables.
    Base.metadata.drop_all(bind=engine)
    init_db()


@responses.activate
def test_refresh_creates_new_jobs_and_dedups_on_second_run():
    responses.add(
        responses.GET,
        "https://remotive.com/api/remote-jobs",
        json={"jobs": [{
            "title": "Backend Engineer",
            "company_name": "TestCo",
            "candidate_required_location": "Anywhere",
            "description": "v1 description",
            "url": "https://remotive.com/remote-jobs/eng/backend-1",
            "publication_date": "2026-06-01T00:00:00",
            "tags": ["python"],
        }]},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://remoteok.com/api",
        json=[{"legal": "disclaimer"}],
        status=200,
    )

    stats = refresh.run_refresh()
    assert stats["new"] == 1
    assert stats["updated"] == 0

    session = SessionLocal()
    try:
        assert session.query(Job).count() == 1
        job = session.query(Job).first()
        assert job.title == "Backend Engineer"
        assert job.description == "v1 description"
    finally:
        session.close()


@responses.activate
def test_refresh_second_run_updates_instead_of_duplicating():
    # First run
    responses.add(
        responses.GET,
        "https://remotive.com/api/remote-jobs",
        json={"jobs": [{
            "title": "Backend Engineer",
            "company_name": "TestCo",
            "candidate_required_location": "Anywhere",
            "description": "v1 description",
            "url": "https://remotive.com/remote-jobs/eng/backend-1",
            "publication_date": "2026-06-01T00:00:00",
            "tags": ["python"],
        }]},
        status=200,
    )
    responses.add(responses.GET, "https://remoteok.com/api", json=[], status=200)
    refresh.run_refresh()

    # Second run: SAME posting (same apply_url) but description changed --
    # must update the existing row, not create a duplicate.
    responses.add(
        responses.GET,
        "https://remotive.com/api/remote-jobs",
        json={"jobs": [{
            "title": "Backend Engineer",
            "company_name": "TestCo",
            "candidate_required_location": "Anywhere",
            "description": "v2 description -- edited",
            "url": "https://remotive.com/remote-jobs/eng/backend-1",
            "publication_date": "2026-06-01T00:00:00",
            "tags": ["python"],
        }]},
        status=200,
    )
    responses.add(responses.GET, "https://remoteok.com/api", json=[], status=200)
    stats = refresh.run_refresh()

    assert stats["new"] == 0
    assert stats["updated"] == 1

    session = SessionLocal()
    try:
        assert session.query(Job).count() == 1  # still just one row, not two
        job = session.query(Job).first()
        assert job.description == "v2 description -- edited"
    finally:
        session.close()


@responses.activate
def test_refresh_one_source_failing_does_not_block_others():
    # Remotive is completely unreachable (no mock registered -> connection
    # error), RemoteOK works fine. The refresh must still succeed overall.
    responses.add(
        responses.GET,
        "https://remoteok.com/api",
        json=[{
            "id": "1", "position": "DevOps Engineer", "company": "OtherCo",
            "location": "Remote", "url": "https://remoteok.com/remote-jobs/1",
            "date": "2026-06-05T00:00:00", "tags": ["aws"],
        }],
        status=200,
    )
    # Deliberately do NOT register a response for remotive.com -> it will fail.

    stats = refresh.run_refresh()
    assert "remotive" in stats["sources_failed"]
    assert stats["new"] == 1  # RemoteOK's job still got saved

    session = SessionLocal()
    try:
        assert session.query(Job).filter_by(source="remoteok").count() == 1
    finally:
        session.close()
