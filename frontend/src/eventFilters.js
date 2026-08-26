// Frontend-only cleanup of the backend's raw search results.

// The backend can return multiple rows for the same event_id (e.g. a
// recurring event with several occurrences all sharing one id - see
// postgre_io.py's docstring on why (event_id, date, date_time) rather than
// event_id alone is the real identity). For the main page we only want one
// card per id, so keep just the first occurrence in result order.
export function dedupeEventsById(events) {
  const seen = new Set();
  const deduped = [];
  for (const event of events) {
    if (seen.has(event.event_id)) continue;
    seen.add(event.event_id);
    deduped.push(event);
  }
  return deduped;
}

// Drops any event whose title exactly matches (case-insensitive, trimmed)
// an entry in the blacklist.
export function excludeBlacklistedEvents(events, blacklist) {
  const blacklisted = new Set(blacklist.map((name) => name.trim().toLowerCase()));
  return events.filter((event) => !blacklisted.has((event.title || "").trim().toLowerCase()));
}
