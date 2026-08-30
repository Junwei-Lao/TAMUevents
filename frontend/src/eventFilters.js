// Frontend-only cleanup of the backend's raw search results.

// The backend can return multiple rows for what's really the same event -
// not just repeated event_ids (see postgre_io.py's docstring on why
// (event_id, date, date_time) rather than event_id alone is the real
// identity for a single scraped listing), but also entirely distinct
// event_ids/urls for what's clearly the same listing (same title, same
// start/end date). event_id and url both turn out to be unreliable for
// this, so identity here is (title, start_date, end_date) instead - two
// events with the same name running the same day(s) are treated as the
// same event, keeping the first occurrence.
export function getEventIdentityKey(event) {
  const title = (event.title || "").trim().toLowerCase();
  return `${title}|${event.start_date || ""}|${event.end_date || ""}`;
}

export function dedupeEvents(events) {
  const seen = new Set();
  const deduped = [];
  for (const event of events) {
    const key = getEventIdentityKey(event);
    if (seen.has(key)) continue;
    seen.add(key);
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
