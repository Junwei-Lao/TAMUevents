# TAMU Events Frontend

React + Vite frontend for browsing TAMU calendar events, filtered by date range.

Browser tab icon: `public/favicon.svg`, a single-color (maroon `#500000`)
calendar glyph - intentionally hardcoded rather than tied to the selectable
theme color below, so the tab icon stays a stable brand mark regardless of
which accent a visitor picks.

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
uvicorn backend:app --port 9191
```

and set `VITE_API_BASE_URL=http://localhost:9191/api` in `frontend/.env`
(copy `.env.example`). 9191 matches `src/main.py`'s default and the
`nginx_config/` deployment setup - keep it in sync with those if it changes.

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
  - **Dedupe by (title, start_date, end_date)** - the backend can return
    multiple rows for what's really the same event: not just repeated
    `event_id`s (see `postgre_io.py`'s docstring on why its real identity
    key is `(event_id, date, date_time)`, not `event_id` alone), but also
    entirely distinct `event_id`s/urls for what's clearly the same listing
    scraped more than once. Neither `event_id` nor `url` turned out to be
    reliable identity, so `getEventIdentityKey` in `eventFilters.js` keys on
    the event's title plus its `start_date`/`end_date` instead - same name,
    same day(s), same event - keeping the first occurrence.
  - **Name blacklist** - events whose title exactly matches (case-insensitive)
    an entry in `src/eventNameBlacklist.js`'s `EVENT_NAME_BLACKLIST` are
    dropped. This is a frontend-only exclusion (no backend change) - edit
    that file's entries to the real titles you want to exclude.

## Settings (gear icon, top-right)

Opens a right-side drawer. Unlike search results, everything here persists
across a refresh via `localStorage` (`src/hooks/useLocalStorageState.js`).

- **Theme Color** - 6 selectable accent colors (`src/themes.js`), applied by
  setting `data-theme` on `<html>` (see `applyTheme`); `index.css` derives
  `--accent-dark` / `--accent-soft` / `--accent-text` from each theme's
  `--accent` with `color-mix()`. Add more by adding entries to `THEMES` plus
  a matching `[data-theme="..."]` block in `index.css`.
- **Appearance** - Light/Dark toggle, right under Theme Color. Applied by
  setting `data-color-mode="dark"` on `<html>` (`src/colorMode.js`), which
  `index.css` uses to redefine the neutral palette (`--bg`, `--card-bg`,
  `--border`, `--text`, `--text-muted`) and the accent derivatives above for
  dark backgrounds.
- **View** - switches the main page between the day-by-day **List** and a
  month **Calendar** (`react-big-calendar`, `src/components/EventCalendar.jsx`).
  The calendar auto-jumps to the month of the earliest result whenever a new
  search completes, but otherwise leaves manual navigation alone.
- **Deleted Events** - opens a sub-page with two tabs, **By Event** (events
  removed individually, restorable one at a time) and **By Name** (event
  names removed entirely, restorable by name). Both lists are the same ones
  written to by the trash icons below - "Restore" just removes the entry
  from the corresponding `localStorage` list.
- **About Us** - opens `src/aboutUs.js`'s `ABOUT_US_URL` (currently a
  placeholder) in a new tab.

### Per-event delete icons

Hovering an event (list card or calendar event bar) reveals two icons at
its right edge:

- Plain trash - removes just this event (records `{key, title, date}` in
  the `deletedEvents` list, `key` being the same `(title, start_date,
  end_date)` identity the dedupe pass above uses). A different event with a
  different title or on different dates isn't affected.
- Trash with an "ALL" badge - removes every event with this exact title
  (records the title in the `deletedEventNames` list). This is a
  user-editable list, separate from the developer-maintained
  `EVENT_NAME_BLACKLIST` above, though both are applied together.

Both apply live against whatever the last search returned (`App.jsx`'s
`visibleEvents`), so deleting/restoring updates the main page immediately
without re-running the search - restoring only brings an event back if it's
still part of the last fetched results.

## Announcement panel

On load, if `announcement/` has any `announcement_<year>_<month>_<day>.txt`
files, the one with the latest date is shown as a centered modal with its
text (one paragraph, read verbatim - `src/announcements.js` picks the file
via Vite's `import.meta.glob` at build time, there's no backend endpoint for
this) plus a "Never show this announcement again" checkbox and a Confirm
button.

- **Confirm** alone just closes it for the current page load - it reappears
  next visit.
- Checking **"Never show this announcement again"** before confirming
  additionally persists that specific file's path to `localStorage`
  (`dismissedAnnouncementId`), so *that* announcement won't show again - but
  dropping a newer-dated file into `announcement/` still shows once,
  since it's compared by file identity, not a single blanket flag.

To publish a new announcement, add a new `announcement_YYYY_M_D.txt` file
(old ones can stay for history, only the latest is ever shown).
