"""
db.py

Reads DATABASE_URL from the environment (via .env locally, or a real env
var on Render/GitHub Actions). Defaults to a local SQLite file if unset,
purely so `python main.py` or `pytest` work out of the box with zero setup.

In production, DATABASE_URL should point at your Aiven Postgres instance,
e.g.:
    postgresql://user:password@host:port/dbname?sslmode=require

Both refresh.py (run by GitHub Actions) and main.py (run on Render) import
this same module and must point at the SAME DATABASE_URL for the cache to
actually work as a shared cache -- if they disagree, main.py will read
from an empty/different database than the one refresh.py wrote to.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _normalize_database_url(url: str) -> str:
    """
    SQLAlchemy 2.x dropped support for the `postgres://` scheme alias --
    it only recognizes `postgresql://` now. Several hosted providers
    (Aiven, Heroku, and others) still hand out `postgres://` URLs in parts
    of their UI even though the underlying database is identical, so this
    self-corrects the scheme regardless of which form gets pasted into
    .env, Render's dashboard, or a GitHub secret. Without this, you get a
    cryptic `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`
    instead of an obvious fix.
    """
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_database_url(
    os.environ.get("DATABASE_URL", "sqlite:///./local_dev.db")
)

# SQLite needs this flag for use across threads (FastAPI's request handling);
# Postgres doesn't accept it, so only pass it for the local-dev fallback.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Creates tables if they don't exist yet. Safe to call on every startup."""
    from models import Base
    Base.metadata.create_all(bind=engine)