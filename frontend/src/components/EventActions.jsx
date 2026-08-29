import TrashIcon from "./TrashIcon.jsx";

// The two hover-reveal trash buttons shared by the list card and the
// calendar event cell. `compact` shrinks them to fit a calendar month
// cell's single-line event bar.
export default function EventActions({ event, onDeleteByUrl, onDeleteByName, compact = false }) {
  const stop = (fn) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    fn(event);
  };

  return (
    <span className={`event-actions ${compact ? "event-actions--compact" : ""}`}>
      <button
        type="button"
        className="icon-btn icon-btn--danger"
        title="Remove this event"
        aria-label={`Remove "${event.title}"`}
        onClick={stop(onDeleteByUrl)}
      >
        <TrashIcon />
      </button>
      <button
        type="button"
        className="icon-btn icon-btn--danger"
        title={`Remove all events named "${event.title}"`}
        aria-label={`Remove all events named "${event.title}"`}
        onClick={stop(onDeleteByName)}
      >
        <TrashIcon all />
      </button>
    </span>
  );
}
