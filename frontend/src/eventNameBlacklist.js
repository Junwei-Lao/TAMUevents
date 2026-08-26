// Event titles to drop from search results on the frontend, without
// touching the backend. Matching is case-insensitive and trims whitespace,
// but otherwise requires an exact match against event.title. Fill in real
// titles as needed.
export const EVENT_NAME_BLACKLIST = [
  "CLOSED",
  "Closed",
  "closed",
];
