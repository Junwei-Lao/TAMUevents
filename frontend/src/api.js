// API contract implemented by src/helpers/backend.py - see
// docs/front_back_contract.md for the authoritative version.
//
// POST {API_BASE_URL}/events/search
// Request body:
//   {
//     "start_date": "YYYY-MM-DD",
//     "end_date": "YYYY-MM-DD",
//     "topic_taxomony": { "<parent category>": ["<leaf>", ...], ... },
//     "event_type": { "<parent category>": ["<leaf>", ...], ... },
//     "categories": ["<value>", ...],
//     "categories_audience": ["<value>", ...]
//   }
// All four filter fields are always present, but an empty {} / [] means
// "All" (no filter on that field) - backend.py's SearchRequest and
// postgre_io.search_events (docs/back_db_contract.md) both treat an
// absent/empty field that way. See App.jsx's buildRequestBody.
//
// Response body:
//   { "events": [ <Event>, ... ] }
// where <Event> is the JSON form of src/helpers/schema.py's Event dataclass,
// plus the `start_date` / `end_date` columns postgre_io.py stores alongside
// it (used here for day-by-day grouping).

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
