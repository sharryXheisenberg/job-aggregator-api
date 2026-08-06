# Jobs Aggregation API

Search job postings aggregated from Greenhouse, Lever, RemoteOK, and
Remotive, normalized to one unified schema, served from a cache that's kept
fresh by a scheduled background refresh -- not fetched live per-request.

## Why cache-and-serve, not fetch-on-request

Every subscriber hitting `/jobs/search` sees the same underlying data, and
that data only changes a few times a day. Fetching live from four different
source APIs on every single request would be slow, and would hammer sources
that have their own rate limits. Instead:

- `refresh.py` runs on a schedule (via GitHub Actions, `.github/workflows/refresh.yml`)
  and pulls from every registered source, writing results into Postgres.
- `main.py` (the actual API, deployed on Render) only ever reads from that
  same Postgres -- fast, and immune to a source going down or rate-limiting
  mid-request.

**Both must point at the same `DATABASE_URL`** -- if they don't, the API
serves from an empty/different database than the one `refresh.py` wrote to.

## Architecture: OCP + LSP, same pattern as the bank statement parser

- **`sources/base.py`** defines `JobSource`, an abstract base every source
  subclasses, and `CanonicalJob` -- the exact schema every source's
  `.fetch()` must return, regardless of how different each provider's raw
  JSON looks.
  - **LSP**: `refresh.py` calls every source exactly the same way --
    `source.fetch(tracked_companies)` -- whether it's a company-scoped
    source (Greenhouse/Lever, which filter the list internally) or a
    feed-based source (RemoteOK/Remotive, which ignore the list entirely).
    The caller never branches on which kind of source it's talking to.
- **`sources/__init__.py`** auto-discovers every `JobSource` subclass at
  import time.
  - **OCP**: adding a 5th source (once you find one with a real
    public/sanctioned endpoint -- see the note on foundit.in below) means
    writing one new file. Nothing else changes.

## Project layout

```
jobs_aggregator_api/
├── requirements.txt
├── .env.example
├── main.py                      # FastAPI app: search / detail / source-status endpoints
├── db.py                        # SQLAlchemy engine/session (DATABASE_URL-driven)
├── models.py                    # Job, TrackedCompany tables
├── refresh.py                   # the script GitHub Actions runs on a schedule
├── sources/
│   ├── __init__.py              # auto-discovers JobSource subclasses
│   ├── base.py                  # JobSource ABC + CanonicalJob contract
│   ├── greenhouse_source.py     # company-scoped
│   ├── lever_source.py          # company-scoped
│   ├── remoteok_source.py       # feed-based
│   └── remotive_source.py       # feed-based
├── scripts/
│   └── add_company.py           # CLI: register a Greenhouse/Lever company to track
├── .github/workflows/refresh.yml
└── tests/
    ├── test_sources.py          # each source against mocked realistic API responses
    └── test_refresh.py          # dedup/upsert logic against a real database
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL (Postgres); leave RAPIDAPI_PROXY_SECRET blank locally
```

## Adding companies to track (Greenhouse/Lever)

```bash
python scripts/add_company.py --source greenhouse --slug airbnb --name "Airbnb"
python scripts/add_company.py --source lever --slug netflix --name "Netflix"
```

Find a company's slug from its careers page URL: `boards.greenhouse.io/<slug>`
or `jobs.lever.co/<slug>`.

RemoteOK and Remotive need no company registration -- they're full feeds.

## Run

```bash
python refresh.py       # pull fresh data from all sources into the database
python main.py           # start the API
# or: uvicorn main:app --reload --port 8000
```

## Use

```bash
curl "http://localhost:8000/jobs/search?keywords=python&remote=true&limit=10"
curl "http://localhost:8000/jobs/12345abc..."
curl "http://localhost:8000/jobs-meta/sources"
```

Interactive API docs: `http://localhost:8000/docs`

## Testing notes

`tests/test_sources.py` verifies each source's parsing/normalization logic
against **mocked** responses shaped like each provider's real, documented
API output -- these are not live network calls. `tests/test_refresh.py`
verifies the dedup/upsert logic end-to-end against a real database.

**Before relying on this in production**, run a real live-network smoke
test from an environment with normal internet access:
```bash
python refresh.py
```
and check the logs for `sources_failed` -- this sandbox's own network
access is restricted to package registries, so the source parsers have
only been validated against realistic mocked payloads here, not the actual
live Greenhouse/Lever/RemoteOK/Remotive endpoints.

```bash
pytest tests/ -v
```

## Known limitations / next steps

- **foundit.in was deliberately excluded.** It has no officially sanctioned
  public API -- available "integrations" are third-party scraper wrappers
  (Apify, RapidAPI listings) using proxy-managed browser sessions against
  Foundit's frontend, unsanctioned by their ToS. Not included here for the
  same reason the social-media-scraper category was ruled out earlier in
  this project's planning.
- No OCR/scanned-content concerns here (unlike the bank parser), but each
  source's JSON shape can change without notice -- `test_sources.py`'s
  mocked-response tests will catch a *known* shape drift only if you update
  the mocks to match; a genuinely new/undocumented shape change from a
  source would need a live smoke test to catch.
- Salary data is inconsistent across sources (Greenhouse/Lever rarely
  expose it in the public API; RemoteOK sometimes does; Remotive doesn't).
  `salary_min`/`salary_max` will often be `null` -- that's expected, not a bug.
- No automated tests for `main.py`'s endpoints yet (validated manually
  against a real local Postgres instance during development) -- worth
  adding `tests/test_api.py` with FastAPI's `TestClient` before relying on
  this in production.
- Production-readiness items from the bank parser project apply equally
  here: structured logging is present in `refresh.py` but not `main.py`
  yet, no rate limiting beyond RapidAPI's own gateway, no Dockerfile, no
  Sentry/monitoring.
