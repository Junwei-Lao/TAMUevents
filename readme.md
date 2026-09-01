# TAMUEvent

If you're looking to meet new people, find interesting activities, or just
figure out what's happening around campus, attending events can be a great
way to do that. But the university's own event calendar makes that harder
than it should be - there are a lot of events, and the categorization can be
difficult to navigate.

**TAMUEvent** is a school event search engine built to make finding
relevant events easier: it scrapes TAMU's public event sources, automatically
classifies every event by topic and type using an LLM, and serves it all
through a fast, filterable search UI at [tamuevent.com](https://tamuevent.com).

## How it works

```
                     nightly, 2am America/Chicago
 ┌─────────────┐   scrape    ┌─────────────┐   tag    ┌─────────────┐
 │ TAMU Calendar│ ──────────▶│             │ ───────▶ │             │
 │  TAMU ERS    │            │ fetch_events │          │   tagging   │
 └─────────────┘            └─────────────┘          └──────┬──────┘
                                                              │ upsert
                                                              ▼
                                                       ┌─────────────┐
                                                       │  PostgreSQL │
                                                       └──────┬──────┘
                                                              │ search_events
                                                              ▼
 ┌─────────────┐   POST /api/events/search   ┌─────────────────────┐
 │ React (Vite) │ ───────────────────────────▶│  FastAPI  (backend) │
 │   frontend   │◀───────────────────────────  └─────────────────────┘
 └─────────────┘         matching events
```

1. **Scrape** (`src/helpers/fetch_events.py`) - pulls events from two public
   TAMU sources: the [TAMU events calendar](https://calendar.tamu.edu) (JSON
   feeds per group, revisited on a cadence) and
   [TAMU ERS](https://ers.tamu.edu) (a scraped ASPX listing page). Both are
   normalized into the shared `Event` schema.
2. **Tag** (`src/helpers/tagging.py`) - every new event is classified into a
   `topics` (1-3 labels) and `event_type` (1 label) taxonomy. A deterministic
   keyword pass runs first (matching taxonomy leaf phrases against the
   event's own text), then a DeepSeek LLM call fills in and validates the
   rest - so a bad/failed API call never means an event goes untagged. See
   [docs/classification.md](docs/classification.md) for the full taxonomy,
   prompt design, and fallback rules.
3. **Store** (`src/helpers/postgre_io.py`) - tagged events are upserted into
   Postgres. Topics are packed as per-category bitflags (one 32-bit column
   per top-level category) rather than one column per leaf label, so
   filtering is index-friendly `bit AND` instead of array/text search. See
   [docs/back_db_contract.md](docs/back_db_contract.md).
4. **Refresh** (`src/main.py`) - a nightly APScheduler job re-scrapes
   everything, diffs it against the DB's last known state, and tags only
   what's genuinely new - existing events just get cheap column updates for
   rescheduling/cancellation, not a full re-tag.
5. **Serve** (`src/helpers/backend.py`) - a FastAPI app exposes
   `POST /api/events/search`, translating the frontend's filter payload
   (topics/event type/categories/audience + date range) into a
   `postgre_io.search_events` query. See
   [docs/front_back_contract.md](docs/front_back_contract.md).
6. **Search** ([frontend/](frontend/)) - a React + Vite single-page app with
   date-range and multi-select filters, list/calendar views, light/dark
   themes, and per-event hide/undo, all filtering client-side once results
   come back. See [frontend/README.md](frontend/README.md) for the full UI
   behavior.

## Project layout

```
src/helpers/
  fetch_events.py   scrapes TAMU calendar + ERS into the Event schema
  tagging.py        keyword pass + DeepSeek classification (topics, event_type)
  schema.py         Event dataclass, taxonomy definitions, bitflag encode/decode
  postgre_io.py      Postgres schema, upserts, search_events query builder
  backend.py        FastAPI app (POST /api/events/search)
src/main.py         entry point: runs the backend + nightly refresh scheduler
frontend/           React + Vite search UI (see frontend/README.md)
docs/               data contracts and the classification spec
data/               scrape/tag pipeline output, category/audience pools, logs
nginx_config/       nginx + systemd deployment configs for tamuevent.com
tests/              pytest suite for fetching, tagging, and Postgres layers
```

## Running it locally

### Backend

Requires Python 3.10+ and a running PostgreSQL instance.

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows; use `source .venv/bin/activate` on Linux/macOS
pip install -r requirements.txt
```

Create a `.env` file at the repo root:

```
DEEPSEEK_API_KEY=...
db_username=...
db_password=...
# optional, default shown:
# db_host=localhost
# db_port=5432
```

One-time pipeline bootstrap (only needed before the database has any data):

```bash
cd src/helpers
python fetch_events.py    # scrapes into data/events.json / data/ers_events.json
python tagging.py         # or call tag_all_events() / tag_all_ers_events() to tag them
python postgre_io.py      # initialize_database() creates the DB/tables and loads tagged data
```

Then run the backend (from `src/`, so the nightly refresh scheduler is
included):

```bash
cd src
python main.py
```

This starts the FastAPI app on `http://localhost:9191` and schedules the
nightly re-scrape/re-tag job. To run just the API without the scheduler:

```bash
cd src/helpers
uvicorn backend:app --port 9191
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. By default it talks to a built-in mock
(`src/mock/sampleEvents.json`) so the UI works standalone; point
`VITE_API_BASE_URL` in `frontend/.env` at `http://localhost:9191/api` to hit
the real backend instead. Full details in
[frontend/README.md](frontend/README.md).

### Tests

```bash
pytest
```

## Deployment

[nginx_config/README.md](nginx_config/README.md) has the full walkthrough
for serving the built frontend and the FastAPI backend from one server
behind nginx, with Let's Encrypt HTTPS and optional Cloudflare real-IP
restoration - this is how [tamuevent.com](https://tamuevent.com) is deployed.

## Tech stack

- **Backend**: Python, FastAPI, Postgres (`psycopg2`), APScheduler, DeepSeek
  API for event classification
- **Frontend**: React, Vite, `react-big-calendar`, `react-day-picker`
- **Deployment**: nginx, systemd, Let's Encrypt, Cloudflare
