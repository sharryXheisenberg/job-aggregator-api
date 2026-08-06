"""
tests/test_sources.py

Tests each JobSource against MOCKED responses shaped like each provider's
real, documented API output (Greenhouse/Lever board APIs, RemoteOK/Remotive
feeds). This sandbox's network access is restricted to package registries,
so these are NOT live network calls -- they verify the parsing/normalization
logic is correct against realistic payloads. A live smoke test against the
real endpoints (`python refresh.py` from an environment with normal
internet access) is still recommended before relying on this in production.
"""

import responses

from sources.greenhouse_source import GreenhouseSource
from sources.lever_source import LeverSource
from sources.remoteok_source import RemoteOKSource
from sources.remotive_source import RemotiveSource


class FakeCompany:
    """Stand-in for a TrackedCompany row, avoids needing a real DB session in these tests."""
    def __init__(self, source, company_slug, display_name, active=True):
        self.source = source
        self.company_slug = company_slug
        self.display_name = display_name
        self.active = active


@responses.activate
def test_greenhouse_source_parses_and_normalizes():
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/airbnb/jobs",
        json={
            "jobs": [
                {
                    "title": "Senior Backend Engineer, Remote",
                    "location": {"name": "Remote - US"},
                    "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/12345",
                    "content": "<p>Build cool stuff.</p>",
                    "updated_at": "2026-06-15T10:00:00-07:00",
                    "departments": [{"name": "Engineering"}],
                }
            ]
        },
        status=200,
    )

    companies = [FakeCompany("greenhouse", "airbnb", "Airbnb")]
    jobs = GreenhouseSource().fetch(companies)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Backend Engineer, Remote"
    assert job.company == "Airbnb"
    assert job.remote is True  # "Remote" appears in title/location
    assert job.source == "greenhouse"
    assert job.posted_date == "2026-06-15"
    assert job.tags == ["Engineering"]
    assert job.apply_url.endswith("/12345")


@responses.activate
def test_greenhouse_source_ignores_companies_from_other_sources():
    # Even if a Lever company is in the list, GreenhouseSource must not
    # attempt to fetch it -- this is the company-scoping contract.
    companies = [FakeCompany("lever", "netflix", "Netflix")]
    jobs = GreenhouseSource().fetch(companies)
    assert jobs == []


@responses.activate
def test_greenhouse_source_skips_failed_company_without_crashing():
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/deadcompany/jobs",
        json={"error": "not found"},
        status=404,
    )
    companies = [FakeCompany("greenhouse", "deadcompany", "Dead Co")]
    # Must not raise -- one bad company board shouldn't kill the whole fetch.
    jobs = GreenhouseSource().fetch(companies)
    assert jobs == []


@responses.activate
def test_lever_source_parses_and_normalizes():
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/netflix",
        json=[
            {
                "text": "Staff Data Engineer",
                "categories": {"location": "Los Gatos, CA / Remote", "team": "Data Platform"},
                "descriptionPlain": "Own our data pipelines.",
                "hostedUrl": "https://jobs.lever.co/netflix/abc-123",
                "createdAt": 1750000000000,  # ms since epoch
            }
        ],
        status=200,
    )

    companies = [FakeCompany("lever", "netflix", "Netflix")]
    jobs = LeverSource().fetch(companies)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Staff Data Engineer"
    assert job.company == "Netflix"
    assert job.remote is True  # "Remote" appears in location string
    assert job.source == "lever"
    assert job.tags == ["Data Platform"]
    assert job.posted_date is not None  # converted from epoch ms


@responses.activate
def test_remoteok_source_skips_metadata_element():
    responses.add(
        responses.GET,
        "https://remoteok.com/api",
        json=[
            {"legal": "This is a disclaimer, not a job."},  # RemoteOK's known quirk
            {
                "id": "999",
                "position": "Frontend Engineer",
                "company": "Acme Remote Co",
                "location": "Worldwide",
                "salary_min": 90000,
                "salary_max": 130000,
                "description": "Build the UI.",
                "url": "https://remoteok.com/remote-jobs/999",
                "date": "2026-06-20T00:00:00+00:00",
                "tags": ["react", "typescript"],
            },
        ],
        status=200,
    )

    jobs = RemoteOKSource().fetch(tracked_companies=[])  # feed-based, ignores this arg

    assert len(jobs) == 1  # the metadata element must be filtered out
    job = jobs[0]
    assert job.title == "Frontend Engineer"
    assert job.remote is True
    assert job.salary_min == 90000.0
    assert job.tags == ["react", "typescript"]


@responses.activate
def test_remotive_source_parses_and_normalizes():
    responses.add(
        responses.GET,
        "https://remotive.com/api/remote-jobs",
        json={
            "jobs": [
                {
                    "title": "Product Designer",
                    "company_name": "Remotive Test Co",
                    "candidate_required_location": "Anywhere",
                    "description": "Design things.",
                    "url": "https://remotive.com/remote-jobs/design/product-designer-1",
                    "publication_date": "2026-06-18T09:00:00",
                    "tags": ["design", "figma"],
                }
            ]
        },
        status=200,
    )

    jobs = RemotiveSource().fetch(tracked_companies=[])

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Product Designer"
    assert job.company == "Remotive Test Co"
    assert job.remote is True
    assert job.posted_date == "2026-06-18"
    assert job.tags == ["design", "figma"]


@responses.activate
def test_company_scoped_sources_return_empty_list_on_failure_not_exception():
    # Greenhouse/Lever: a bad company board must not raise -- there's
    # per-company granularity to protect (see test above).
    assert GreenhouseSource().fetch([FakeCompany("greenhouse", "x", "X")]) == []
    assert LeverSource().fetch([FakeCompany("lever", "x", "X")]) == []


def test_feed_sources_raise_on_total_failure_by_design():
    # RemoteOK/Remotive: NO mock registered at all (responses not even
    # activated here) -> a real connection attempt will fail. Unlike the
    # company-scoped sources, this SHOULD raise -- there's no per-item
    # granularity to protect, so refresh.py's per-source try/except is
    # meant to catch this and record it in sources_failed. See
    # sources/remoteok_source.py's docstring/comments for the reasoning.
    import pytest
    import requests

    with pytest.raises(requests.exceptions.RequestException):
        RemoteOKSource().fetch([])
    with pytest.raises(requests.exceptions.RequestException):
        RemotiveSource().fetch([])
