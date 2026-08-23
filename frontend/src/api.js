// API contract with the (future) FastAPI backend.
//
// POST {API_BASE_URL}/events/search
// Request body:
//   {
//     "start_date": "YYYY-MM-DD",       // required
//     "end_date": "YYYY-MM-DD",         // required
//     "topics": ["<label>", ...],       // optional, omitted = no filter
//     "event_type": "<label>",          // optional, omitted = no filter
//     "categories": ["<label>", ...],   // optional, omitted = no filter
//     "categories_audience": ["<label>", ...] // optional, omitted = no filter
//   }
// Response body:
//   { "events": [ <Event>, ... ] }
// where <Event> is the JSON form of src/helpers/schema.py's Event dataclass,
// plus the `start_date` / `end_date` columns postgre_io.py stores alongside
// it (used here for day-by-day grouping).
//
// The backend is expected to implement this on top of
// postgre_io.get_events_in_date_range(start_date, end_date), narrowed
// further by array-overlap (topics/categories/categories_audience) and
// equality (event_type) filters when those fields are present.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export async function searchEvents(requestBody) {
  const response = await fetch(`${API_BASE_URL}/events/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody),
  });

  if (!response.ok) {
    throw new Error(`Event search failed (${response.status})`);
  }

  const data = await response.json();
  return data.events || [];
}
