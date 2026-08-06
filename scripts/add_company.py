"""
scripts/add_company.py

Registers a company to track from Greenhouse or Lever. This is the
"expandable list" mechanism -- adding a company is one row in the
database, not a code change or redeploy.

Usage:
    python scripts/add_company.py --source greenhouse --slug airbnb --name "Airbnb"
    python scripts/add_company.py --source lever --slug netflix --name "Netflix"

Finding a company's slug:
    Greenhouse: visit https://boards.greenhouse.io/<slug> -- the slug is
    right there in the URL. Or check the company's careers page; Greenhouse
    embeds usually reveal it in the page source / network requests.
    Lever: same idea, visit https://jobs.lever.co/<slug>.
"""

from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db  # noqa: E402
from models import TrackedCompany  # noqa: E402


def add_company(source: str, slug: str, name: str) -> str:
    init_db()
    session = SessionLocal()
    try:
        existing = (
            session.query(TrackedCompany)
            .filter_by(source=source, company_slug=slug)
            .first()
        )
        if existing:
            return f"Already tracked: {existing.display_name} ({existing.source}/{existing.company_slug})"

        company = TrackedCompany(source=source, company_slug=slug, display_name=name, active=True)
        session.add(company)
        session.commit()
        return f"Added: {name} ({source}/{slug})"
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Register a company to track for job postings.")
    parser.add_argument("--source", required=True, choices=["greenhouse", "lever"])
    parser.add_argument("--slug", required=True, help="The company's board slug, e.g. 'airbnb'")
    parser.add_argument("--name", required=True, help="Display name, e.g. 'Airbnb'")
    args = parser.parse_args()

    print(add_company(args.source, args.slug, args.name))


if __name__ == "__main__":
    main()
