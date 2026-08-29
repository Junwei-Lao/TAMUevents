import { useState } from "react";
import { THEMES } from "../themes.js";
import { ABOUT_US_URL } from "../aboutUs.js";
import DeletedEventsPanel from "./DeletedEventsPanel.jsx";

export default function SettingsDrawer({
  isOpen,
  onClose,
  themeKey,
  onThemeChange,
  viewMode,
  onViewModeChange,
  deletedEventIds,
  deletedEventNames,
  onRestoreById,
  onRestoreByName,
}) {
  const [page, setPage] = useState("main");

  const handleClose = () => {
    onClose();
    setPage("main");
  };

  return (
    <>
      <div
        className={`drawer-overlay ${isOpen ? "drawer-overlay--open" : ""}`}
        onClick={handleClose}
      />
      <aside className={`drawer drawer--right ${isOpen ? "drawer--open" : ""}`}>
        {page === "deleted" ? (
          <DeletedEventsPanel
            deletedEventIds={deletedEventIds}
            deletedEventNames={deletedEventNames}
            onRestoreById={onRestoreById}
            onRestoreByName={onRestoreByName}
            onBack={() => setPage("main")}
          />
        ) : (
          <>
            <div className="drawer-header">
              <h2>Settings</h2>
              <button className="drawer-close-btn" aria-label="Close" onClick={handleClose}>
                &times;
              </button>
            </div>

            <div className="settings-section">
              <h3 className="drawer-section-title">Theme Color</h3>
              <div className="theme-swatch-row">
                {Object.entries(THEMES).map(([key, theme]) => (
                  <button
                    key={key}
                    type="button"
                    className={`theme-swatch ${key === themeKey ? "theme-swatch--active" : ""}`}
                    style={{ background: theme.primary }}
                    aria-label={theme.label}
                    aria-pressed={key === themeKey}
                    title={theme.label}
                    onClick={() => onThemeChange(key)}
                  >
                    {key === themeKey && <span className="theme-swatch-check">&#10003;</span>}
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-section">
              <h3 className="drawer-section-title">View</h3>
              <div className="view-toggle">
                <button
                  type="button"
                  className={`view-toggle-btn ${viewMode === "list" ? "view-toggle-btn--active" : ""}`}
                  onClick={() => onViewModeChange("list")}
                >
                  List
                </button>
                <button
                  type="button"
                  className={`view-toggle-btn ${viewMode === "calendar" ? "view-toggle-btn--active" : ""}`}
                  onClick={() => onViewModeChange("calendar")}
                >
                  Calendar
                </button>
              </div>
            </div>

            <div className="settings-section">
              <button
                type="button"
                className="settings-nav-btn"
                onClick={() => setPage("deleted")}
              >
                <span>Deleted Events</span>
                <span className="settings-nav-btn-count">
                  {deletedEventIds.length + deletedEventNames.length}
                </span>
                <span aria-hidden="true">&rarr;</span>
              </button>
            </div>

            <div className="settings-section">
              <button
                type="button"
                className="settings-nav-btn"
                onClick={() =>
                  window.open(ABOUT_US_URL, "_blank", "noopener,noreferrer")
                }
              >
                <span>About Us</span>
                <span aria-hidden="true">&#8599;</span>
              </button>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
