import { useState } from "react";

export default function AnnouncementPanel({ announcement, onConfirm }) {
  const [neverShowAgain, setNeverShowAgain] = useState(false);

  return (
    <div className="announcement-overlay">
      <div
        className="announcement-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="announcement-title"
      >
        <h2 id="announcement-title">Announcement</h2>
        <p className="announcement-text">{announcement.text}</p>
        <label className="announcement-checkbox">
          <input
            type="checkbox"
            checked={neverShowAgain}
            onChange={(e) => setNeverShowAgain(e.target.checked)}
          />
          Never show this announcement again
        </label>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => onConfirm(neverShowAgain)}
        >
          Confirm
        </button>
      </div>
    </div>
  );
}
