// Selectable theme colors. `primary`/`primaryDark` drive the CSS custom
// properties --accent/--accent-dark (see applyTheme below); `soft` is a
// light tint used for subtle active/hover backgrounds. Values are drawn
// from well-established, accessible modern UI palettes (Tailwind's scale)
// alongside the original TAMU maroon as the default.
export const THEMES = {
  maroon: { label: "Maroon", primary: "#500000", primaryDark: "#3a0000", soft: "#f1e9e9" },
  indigo: { label: "Indigo", primary: "#4f46e5", primaryDark: "#3730a3", soft: "#e0e7ff" },
  teal: { label: "Teal", primary: "#0d9488", primaryDark: "#115e59", soft: "#ccfbf1" },
  emerald: { label: "Emerald", primary: "#059669", primaryDark: "#065f46", soft: "#d1fae5" },
  slate: { label: "Slate", primary: "#334155", primaryDark: "#0f172a", soft: "#f1f5f9" },
  coral: { label: "Coral", primary: "#e11d48", primaryDark: "#9f1239", soft: "#ffe4e6" },
};

export const DEFAULT_THEME_KEY = "maroon";

export function applyTheme(themeKey) {
  const theme = THEMES[themeKey] || THEMES[DEFAULT_THEME_KEY];
  const root = document.documentElement.style;
  root.setProperty("--accent", theme.primary);
  root.setProperty("--accent-dark", theme.primaryDark);
  root.setProperty("--accent-soft", theme.soft);
}
