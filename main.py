"""
main.py

Jobs Aggregation API. Serves job postings cached by refresh.py (run on a
schedule via GitHub Actions) from Greenhouse, Lever, RemoteOK, and
Remotive. NEVER fetches sources live per-request -- always reads from the
database, which is what keeps this fast and immune to a source rate-
limiting or going down mid-request.

Run locally with EITHER:
    python main.py
    uvicorn main:app --reload --port 8000

Environment variables (see .env.example):
    DATABASE_URL           -- required in production (Postgres connection
                              string). Defaults to a local SQLite file if
                              unset, for zero-setup local dev.
    RAPIDAPI_PROXY_SECRET  -- optional. Leave unset for local dev.
    PORT                   -- optional. Defaults to 8000.
"""

from __future__ import annotations
import os
import secrets
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_

from db import SessionLocal, init_db
from models import Job
from sources import SOURCE_REGISTRY

app = FastAPI(
    title="Jobs Aggregation API",
    description="Search job postings aggregated from Greenhouse, Lever, "
                "RemoteOK, and Remotive, normalized to one unified schema.",
    version="1.0.0",
)

RAPIDAPI_PROXY_SECRET = os.environ.get("RAPIDAPI_PROXY_SECRET")


@app.middleware("http")
async def verify_rapidapi_proxy_secret(request: Request, call_next):
    # Same pattern as the bank statement parser: '/' stays open for health
    # checks; everything else requires the RapidAPI gateway's secret header
    # once RAPIDAPI_PROXY_SECRET is actually set in the environment.
    if RAPIDAPI_PROXY_SECRET and request.url.path != "/":
        incoming = request.headers.get("x-rapidapi-proxy-secret", "")
        if not secrets.compare_digest(incoming, RAPIDAPI_PROXY_SECRET):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid RapidAPI proxy secret. "
                                    "This API must be accessed through the "
                                    "RapidAPI marketplace."},
            )
    return await call_next(request)


@app.on_event("startup")
def on_startup():
    init_db()


def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "description": job.description,
        "apply_url": job.apply_url,
        "source": job.source,
        "posted_date": job.posted_date,
        "tags": job.tags.split(",") if job.tags else [],
        "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
        "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
    }


@app.get("/")
def health_check():
    return {"status": "ok", "sources": list(SOURCE_REGISTRY.keys())}


@app.get("/jobs/search")
def search_jobs(
    keywords: Optional[str] = Query(None, description="Matches against title and description"),
    location: Optional[str] = Query(None),
    remote: Optional[bool] = Query(None),
    company: Optional[str] = Query(None),
    source: Optional[str] = Query(None, description=f"One of: {', '.join(SOURCE_REGISTRY.keys())}"),
    tags: Optional[str] = Query(None, description="Comma-separated; matches any of the given tags"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    if source and source not in SOURCE_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid sources: {list(SOURCE_REGISTRY.keys())}.",
        )

    session = SessionLocal()
    try:
        query = session.query(Job)

        if keywords:
            like = f"%{keywords}%"
            query = query.filter(or_(Job.title.ilike(like), Job.description.ilike(like)))
        if location:
            query = query.filter(Job.location.ilike(f"%{location}%"))
        if remote is not None:
            query = query.filter(Job.remote == remote)
        if company:
            query = query.filter(Job.company.ilike(f"%{company}%"))
        if source:
            query = query.filter(Job.source == source)
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            if tag_list:
                query = query.filter(or_(*[Job.tags.ilike(f"%{t}%") for t in tag_list]))

        total = query.count()
        results = (
            query.order_by(Job.last_seen_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "jobs": [job_to_dict(j) for j in results],
        }
    finally:
        session.close()


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job_to_dict(job)
    finally:
        session.close()


@app.get("/jobs-meta/sources")
def sources_status():
    """
    Per-source health snapshot: how many jobs currently cached, and when
    that source was last successfully refreshed. Doubles as a trust signal
    for subscribers ("this data is actually fresh") and a debugging tool
    for you (spot a source silently failing before a subscriber complains).
    """
    session = SessionLocal()
    try:
        result = []
        for source_name in SOURCE_REGISTRY:
            latest = (
                session.query(Job)
                .filter_by(source=source_name)
                .order_by(Job.last_seen_at.desc())
                .first()
            )
            result.append({
                "source": source_name,
                "job_count": session.query(Job).filter_by(source=source_name).count(),
                "last_refreshed": latest.last_seen_at.isoformat() if latest else None,
            })
        return {"sources": result}
    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
