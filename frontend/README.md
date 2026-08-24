# TAMU Events Frontend

React + Vite frontend for browsing TAMU calendar events, filtered by date range.

## Run it

```bash
cd frontend
npm install
npm run dev
```

Opens at http://localhost:5173. In dev mode, `POST /api/events/search` is
served by a mock middleware in `vite.config.js` backed by
`src/mock/sampleEvents.json`, so the UI works before the real backend exists.

## API contract (for the future FastAPI backend)

Authoritative version: `docs/front_back_contract.md` at the repo root.

**`POST /api/events/search`**

Request body:

```json
{
  "start_date": "2026-09-15",
  "end_date": "2026-09-20",
  "topic_taxomony": {
    "STEM & Technology": ["Artificial Intelligence / Machine Learning", "Robotics"]
  },
  "event_type": {
    "Academic / Research": ["Seminar"]
  },
  "categories": ["Academic"],
  "categories_audience": ["Students"]
}
```

- `start_date` / `end_date` are required, ISO 8601 `YYYY-MM-DD` strings, inclusive; `end_date` must be `>= start_date`.
- `topic_taxomony` / `event_type` / `categories` / `categories_audience` are always present (never omitted). Selecting "All" for a section in the UI (the default) sends the *complete* taxonomy/pool for that field rather than leaving it out, since the contract doesn't model an absent field - see `buildRequestBody` in `src/App.jsx`.
- `topic_taxomony` / `event_type` are `{ "<parent category>": ["<leaf>", ...], ... }`, mirroring `TOPIC_TAXONOMY` / `EVENT_TYPE_TAXONOMY` in `src/helpers/schema.py` (ported to the frontend in `src/taxonomy.js` - keep the two in sync by hand). Only parents with at least one selected leaf appear as keys when the user has made an explicit pick.
- `categories` / `categories_audience` are flat arrays - no taxonomy, since those are backend-discovered pools (`postgre_io.py`'s `category_pool` / `audience_pool` tables). The frontend currently uses placeholder options (`A`, `B`, `C`) in `src/taxonomy.js` - swap those for the real pool values once the backend can serve them.

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
      "event_type": "Commencement"
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
- Topics and Event Type are two-level: pressing a parent-category chip
  expands/collapses its leaf chips below it; pressing a leaf toggles it as a
  selected filter value (multi-select, across any number of parents).
  Categories and Audience are flat chip lists (no parent level). Each
  section starts on "All" (no explicit picks).
- Results are grouped day-by-day (using `start_date`) with a header per day,
  each event shown as a card with title, date, and description. Clicking a
  card opens `event.url` in a new tab.
