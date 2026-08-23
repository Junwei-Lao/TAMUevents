import EventCard from "./EventCard.jsx";

function dayHeaderLabel(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function groupEventsByDay(events) {
  const groups = new Map();
  for (const event of events) {
    const key = event.start_date || event.date || "Unknown date";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export default function EventList({ events, isLoading, error }) {
  if (isLoading) {
    return <p className="event-list-status">Loading events...</p>;
  }

  if (error) {
    return <p className="event-list-status event-list-status--error">{error}</p>;
  }

  if (events.length === 0) {
    return (
      <p className="event-list-status">
        No events loaded yet. Use the menu at the top-left to select a date
        range and apply a filter.
      </p>
    );
  }

  const groupedEvents = groupEventsByDay(events);

  return (
    <div className="event-list">
      {groupedEvents.map(([dayKey, dayEvents]) => (
        <section key={dayKey} className="event-day-group">
          <h2 className="event-day-header">
            {/^\d{4}-\d{2}-\d{2}$/.test(dayKey) ? dayHeaderLabel(dayKey) : dayKey}
          </h2>
          <div className="event-day-events">
            {dayEvents.map((event) => (
              <EventCard
                key={`${event.event_id}-${event.date}-${event.date_time}`}
                event={event}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
