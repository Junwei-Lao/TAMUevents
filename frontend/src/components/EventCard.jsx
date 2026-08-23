export default function EventCard({ event }) {
  const openEvent = () => {
    window.open(event.url, "_blank", "noopener,noreferrer");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openEvent();
    }
  };

  return (
    <div
      className="event-card"
      role="link"
      tabIndex={0}
      onClick={openEvent}
      onKeyDown={handleKeyDown}
    >
      <h3 className="event-card-title">{event.title}</h3>
      <p className="event-card-date">
        {event.date}
        {event.date_time ? ` • ${event.date_time}` : ""}
      </p>
      {event.description && (
        <p className="event-card-description">{event.description}</p>
      )}
    </div>
  );
}
