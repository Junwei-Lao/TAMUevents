# TAMU Events Frontend

React + Vite frontend for browsing TAMU calendar events, filtered by date range.

## Run it

```bash
cd frontend
npm install
npm run dev
```

Opens at http://localhost:5173. By default `POST /api/events/search` is
served by a mock middleware in `vite.config.js` backed by
`src/mock/sampleEvents.json`, so the UI works standalone.

To hit the real backend instead, start it from `src/helpers`:

```bash
uvicorn backend:app --port 8000
```

and set `VITE_API_BASE_URL=http://localhost:8000/api` in `frontend/.env`
(copy `.env.example`).

## API contract (implemented by `src/helpers/backend.py`)

Authoritative version: `docs/front_back_contract.md` at the repo root.

**`POST /api/events/search`**

Request body:

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-12-31",
  "topic_taxomony": {
    "STEM & Technology": ["Artificial Intelligence / Machine Learning", "Robotics"]
  },
  "event_type": {
    "Academic / Research": []
  },
  "categories": ["Sports & Athletics"],
  "categories_audience": ["Students"]
}
```

- `start_date` / `end_date` are required, ISO 8601 `YYYY-MM-DD` strings, inclusive; `end_date` must be `>= start_date`.
- `topic_taxomony` / `event_type` / `categories` / `categories_audience` are always present. An **empty** `{}` / `[]` means "All" (no filter on that field) - this matches `backend.py`'s `SearchRequest` defaults and `postgre_io.search_events`'s documented semantics (`docs/back_db_contract.md`: "an absent, `None`, or empty key applies no filter"). The frontend never expands "All" into an explicit full list - see `buildRequestBody` in `src/App.jsx`.
- `topic_taxomony` is `{ "<parent category>": ["<leaf>", ...], ... }`, mirroring `TOPIC_TAXONOMY` in `src/helpers/schema.py` (ported to the frontend in `src/taxonomy.js` - keep the two in sync by hand). Only parents with at least one selected leaf appear as keys.
- `event_type` uses the same `{parent: [leaf, ...]}` shape for contract consistency, but is only ever stored on an `Event` at the **parent-category** level (`tagging.py`'s `_validate_event_type` collapses the model's leaf pick to its parent), so `backend.py` only looks at its parent keys - the leaf arrays are ignored server-side. The UI reflects this: Event Type is a flat pick of parent category names (`EVENT_TYPE_CATEGORIES` in `src/taxonomy.js`, no leaves, no expand), and `App.jsx`'s `buildRequestBody` wraps each selected name as `{name: []}` before sending.
- `categories` / `categories_audience` are flat arrays (no taxonomy) - discovered pools mirrored from `data/category_pool.json` / `data/audience_pool.json` into `src/taxonomy.js`'s `CATEGORY_OPTIONS` / `AUDIENCE_OPTIONS`. Keep those in sync by hand if the pool files change (there's no endpoint yet to fetch them at runtime).

Response body:

```json
{
  "events": [
    {
      "event_id": 372167,
      "group_title": "Academic Calendar",
      "url": "https://calendar.tamu.edu/...",
      "date": "September 15, 2026",
      "date_time": "7:00pm",
      "start_date": "2026-09-15",
      "end_date": "2026-09-15",
      "title": "Commencement and Commissioning",
      "description": "...",
      "location": "Reed Arena",
      "categories": ["Academic Calendar"],
      "categories_audience": ["Faculty", "Staff", "Students"],
      "is_canceled": "",
      "topics": { "Campus & Student Life": ["Traditions"] },
      "event_type": "Ceremony / Tradition"
    }
  ]
}
```

Each item is the JSON form of the `Event` dataclass in
`src/helpers/schema.py`, plus the `start_date` / `end_date` columns that
`src/helpers/postgre_io.py` already stores on `events_before_tagging`
(used here for day-by-day grouping on the main page).

## Behavior notes

- The main page starts empty and stays empty until a filter is applied; it
  does not persist events across a page refresh (no localStorage), by design.
- The triple-line button top-left opens a slide-in panel with a calendar
  range picker plus four filter sections (Topics, Event Type, Categories,
  Audience). "Clear Selection" resets the date range and all filters back to
  their defaults; "Apply Filter" sends the request above and loads results
  into the main page.
- Topics is two-level: each parent category is a split button - pressing the
  label selects/deselects every leaf under it in one press, pressing the
  separate "+"/"−" only expands or collapses the leaf chips below it
  (without changing the selection). Leaf chips toggle individually. Event
  Type, Categories, and Audience are flat chip lists (no parent/leaf split -
  event types have no useful leaf-level filter, see above). Each section
  starts on "All" (no explicit picks - sent as `{}`/`[]`).
- Results are grouped day-by-day (using `start_date`) with a header per day,
  each event shown as a card with title, date, and description. Clicking a
  card opens `event.url` in a new tab.
- Before display, results go through two frontend-only cleanup passes
  (`src/eventFilters.js`, applied in `App.jsx`'s `applyFilter`):
  - **Dedupe by id** - the backend can return multiple rows sharing one
    `event_id` (e.g. a recurring event's separate occurrences all carry the
    same id - see `postgre_io.py`'s docstring on why its real identity key
    is `(event_id, date, date_time)`, not `event_id` alone). Only the first
    occurrence per id is kept.
  - **Name blacklist** - events whose title exactly matches (case-insensitive)
    an entry in `src/eventNameBlacklist.js`'s `EVENT_NAME_BLACKLIST` are
    dropped. This is a frontend-only exclusion (no backend change)
