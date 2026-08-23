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

**`POST /api/events/search`**

Request body:

```json
{
  "start_date": "2026-09-15",
  "end_date": "2026-09-20",
  "topics": ["Artificial Intelligence / Machine Learning"],
  "event_type": "Seminar",
  "categories": ["Academic"],
  "categories_audience": ["Students"]
}
```

- `start_date` / `end_date` are required, ISO 8601 `YYYY-MM-DD` strings, inclusive; `end_date` must be `>= start_date`.
- `topics`, `event_type`, `categories`, `categories_audience` are all optional - omit a field (or leave it unselected, shown as "All" in the UI) to not filter on it.
  `topics` / `categories` / `categories_audience` are arrays (array-overlap match against the Event's array columns, e.g. `postgre_io.get_events_by_topics`'s `&&` semantics); `event_type` is a single string (exact match), matching its type on the `Event` dataclass.
- The frontend's filter dropdowns (Topics, Event Type, Categories, Audience) currently use placeholder options (`All`, `A`, `B`, `C`) in `src/filterOptions.js` - swap those for the real taxonomy/pool values (`tagging.py`'s `TOPIC_TAXONOMY` / `EVENT_TYPE_TAXONOMY`, and the `category_pool` / `audience_pool` tables) once the backend can serve them.

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
      "topics": ["Other STEM"],
      "event_type": "Ceremony"
    }
  ]
}
```

Each item is the JSON form of the `Event` dataclass in
`src/helpers/schema.py`, plus the `start_date` / `end_date` columns that
`src/helpers/postgre_io.py` already stores on `events_before_tagging`
(used here for day-by-day grouping on the main page).

The backend can implement this endpoint directly on top of the existing
`get_events_in_date_range(range_start, range_end)` helper in
`postgre_io.py` — it already returns events whose `[start_date, end_date]`
interval overlaps the requested range, merged with their `topics` /
`event_type` tags.

## Behavior notes

- The main page starts empty and stays empty until a filter is applied; it
  does not persist events across a page refresh (no localStorage), by design.
- The triple-line button top-left opens a slide-in panel with a calendar
  range picker. "Clear Selection" resets the pending selection; "Apply
  Filter" sends the request above and loads results into the main page.
- Results are grouped day-by-day (using `start_date`) with a header per day,
  each event shown as a card with title, date, and description. Clicking a
  card opens `event.url` in a new tab.
