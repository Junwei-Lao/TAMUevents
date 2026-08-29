// Parses a "YYYY-MM-DD" string into a local Date at midnight. Building the
// Date from its parts (rather than `new Date(isoString)`, which parses as
// UTC) avoids the date shifting by a day in timezones behind UTC.
export function parseIsoDateLocal(isoDate) {
  if (!isoDate) return null;
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day);
}
