import { useEffect, useState } from "react";

const PREFIX = "tamuEvents.";

function readStoredValue(key, defaultValue) {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw === null ? defaultValue : JSON.parse(raw);
  } catch {
    return defaultValue;
  }
}

// Settings, theme, and the deleted-event lists all need to survive a page
// refresh (unlike search results, which intentionally reset - see
// App.jsx). This is the one hook all of that persistence goes through:
// state that reads its initial value from localStorage once, and writes
// back on every change.
export function useLocalStorageState(key, defaultValue) {
  const [value, setValue] = useState(() => readStoredValue(key, defaultValue));

  useEffect(() => {
    try {
      window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage unavailable (private browsing, quota, etc.) - the app still
      // works for the current session, it just won't persist.
    }
  }, [key, value]);

  return [value, setValue];
}
