// Frontend-only cleanup of the backend's raw search results.

// The backend can return multiple rows for what's really the same event -
// not just repeated event_ids (see postgre_io.py's docstring on why
// (event_id, date, date_time) rather than event_id alone is the real
// identity for a single scraped listing), but also distinct event_ids that
// point at the same event.url (the same event scraped/listed more than
// once under different ids). event_id isn't a reliable identity for
// display purposes either way, so dedupe on url instead - for the main
// page we only want one card per url, keeping the first occurrence.
export function dedupeEventsByUrl(events) {
  const seen = new Set();
  const deduped = [];
  for (const event of events) {
    if (seen.has(event.url)) continue;
    seen.add(event.url);
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
