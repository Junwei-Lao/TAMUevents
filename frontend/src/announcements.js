// Reads every announcement_<year>_<month>_<day>.txt file out of
// frontend/announcement/ at build time (Vite's import.meta.glob - there's
// no backend endpoint for this, files just live in the repo) and picks
// whichever one is dated latest. Drop a new file in that folder to publish
// a new announcement; the old ones are kept around for history but ignored.
const files = import.meta.glob("../announcement/*.txt", {
  eager: true,
  query: "?raw",
  import: "default",
});

const FILENAME_RE = /announcement_(\d{4})_(\d{1,2})_(\d{1,2})\.txt$/;

function parseAnnouncements() {
  const entries = [];
  for (const [path, content] of Object.entries(files)) {
    const match = path.match(FILENAME_RE);
    if (!match) continue;
    const [, year, month, day] = match;
    const date = new Date(Number(year), Number(month) - 1, Number(day));
    entries.push({ id: path, date, text: content.trim() });
  }
  return entries.sort((a, b) => b.date - a.date);
}

// { id, date, text } for the most recently dated announcement, or null if
// src/announcement/ has no matching files.
export function getLatestAnnouncement() {
  return parseAnnouncements()[0] || null;
}
