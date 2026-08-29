import EventCard from "./EventCard.jsx";
import { parseIsoDateLocal } from "../dateUtils.js";

function dayHeaderLabel(isoDate) {
  return parseIsoDateLocal(isoDate).toLocaleDateString("en-US", {
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

export default function EventList({ events, onDeleteById, onDeleteByName }) {
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
                onDeleteById={onDeleteById}
                onDeleteByName={onDeleteByName}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
