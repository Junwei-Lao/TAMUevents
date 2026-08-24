// API contract with the (future) FastAPI backend - see
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
// All four filter fields are always present - "All" (no explicit picks) is
// sent as the complete taxonomy/pool for that field rather than an omitted
// key, since the contract doesn't model an optional/absent field. See
// App.jsx's buildRequestBody.
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
