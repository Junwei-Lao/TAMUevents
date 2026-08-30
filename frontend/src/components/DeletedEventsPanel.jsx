import { useState } from "react";

export default function DeletedEventsPanel({
  deletedEvents,
  deletedEventNames,
  onRestoreEvent,
  onRestoreByName,
  onBack,
}) {
  const [tab, setTab] = useState("byEvent");

  return (
    <div className="deleted-panel">
      <div className="deleted-panel-header">
        <button className="back-btn" onClick={onBack} aria-label="Back to settings">
          &larr;
        </button>
        <h2>Deleted Events</h2>
      </div>

      <div className="deleted-tabs">
        <button
          type="button"
          className={`deleted-tab ${tab === "byEvent" ? "deleted-tab--active" : ""}`}
          onClick={() => setTab("byEvent")}
        >
          By Event ({deletedEvents.length})
        </button>
        <button
          type="button"
          className={`deleted-tab ${tab === "byName" ? "deleted-tab--active" : ""}`}
          onClick={() => setTab("byName")}
        >
          By Name ({deletedEventNames.length})
        </button>
      </div>

      {tab === "byEvent" ? (
        deletedEvents.length === 0 ? (
          <p className="deleted-empty">No individually removed events.</p>
        ) : (
          <ul className="deleted-list">
            {deletedEvents.map((entry) => (
              <li key={entry.key} className="deleted-row">
                <div className="deleted-row-info">
                  <span className="deleted-row-title">{entry.title}</span>
                  <span className="deleted-row-meta">{entry.date}</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-small"
                  onClick={() => onRestoreEvent(entry.key)}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        )
      ) : deletedEventNames.length === 0 ? (
        <p className="deleted-empty">No event names removed.</p>
      ) : (
        <ul className="deleted-list">
          {deletedEventNames.map((name) => (
            <li key={name} className="deleted-row">
              <div className="deleted-row-info">
                <span className="deleted-row-title">{name}</span>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                onClick={() => onRestoreByName(name)}
              >
                Restore
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
