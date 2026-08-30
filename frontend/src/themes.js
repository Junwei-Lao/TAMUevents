// Selectable theme colors - just a label plus the one "primary" hex per
// theme (used for the settings swatch itself and as the CSS --accent
// value). Every derived shade (--accent-dark, --accent-soft, --accent-text)
// is computed from --accent via color-mix() in index.css, so there's
// nothing else to keep in sync here. Values are drawn from well-established,
// accessible modern UI palettes (Tailwind's scale) alongside the original
// TAMU maroon as the default.
export const THEMES = {
  maroon: { label: "Maroon", primary: "#500000" },
  indigo: { label: "Indigo", primary: "#4f46e5" },
  teal: { label: "Teal", primary: "#0d9488" },
  emerald: { label: "Emerald", primary: "#059669" },
  slate: { label: "Slate", primary: "#334155" },
  coral: { label: "Coral", primary: "#e11d48" },
};

export const DEFAULT_THEME_KEY = "maroon";

// Sets data-theme on <html> - index.css's `[data-theme="..."]` rules key
// off this to set --accent (see THEMES above for the matching hex values,
// which must stay in sync by hand).
export function applyTheme(themeKey) {
  document.documentElement.dataset.theme = THEMES[themeKey] ? themeKey : DEFAULT_THEME_KEY;
}
