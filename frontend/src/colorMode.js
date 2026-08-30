// Light/dark UI mode. Applied via a `data-color-mode` attribute on <html> -
// index.css keys its dark-palette overrides off `[data-color-mode="dark"]`.
// Light is the default and has no attribute at all (simpler than writing
// out a `[data-color-mode="light"]` selector for every override).
export const DEFAULT_COLOR_MODE = "light";

export function applyColorMode(mode) {
  const root = document.documentElement;
  if (mode === "dark") {
    root.setAttribute("data-color-mode", "dark");
  } else {
    root.removeAttribute("data-color-mode");
  }
}
