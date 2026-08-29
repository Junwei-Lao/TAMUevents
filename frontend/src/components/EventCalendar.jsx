import { useMemo } from "react";
import { Calendar, dateFnsLocalizer } from "react-big-calendar";
import { format, parse, startOfWeek, getDay } from "date-fns";
import { enUS } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
import EventActions from "./EventActions.jsx";
import { parseIsoDateLocal } from "../dateUtils.js";

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: () => startOfWeek(new Date(), { weekStartsOn: 0 }),
  getDay,
  locales: { "en-US": enUS },
});

function toCalendarEvents(events) {
  return events
    .filter((event) => event.start_date)
    .map((event) => ({
      id: `${event.event_id}-${event.date}-${event.date_time}`,
      title: event.title,
      start: parseIsoDateLocal(event.start_date),
      end: parseIsoDateLocal(event.end_date || event.start_date),
      allDay: true,
      resource: event,
    }));
}

function EventCell({ event, onDeleteById, onDeleteByName }) {
  const original = event.resource;
  const openEvent = () => window.open(original.url, "_blank", "noopener,noreferrer");

  return (
    <span className="calendar-event-cell" onClick={(e) => e.stopPropagation()}>
      <span
        className="calendar-event-title"
        role="link"
        tabIndex={0}
        onClick={openEvent}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && openEvent()}
      >
        {event.title}
      </span>
      <EventActions
        event={original}
        onDeleteById={onDeleteById}
        onDeleteByName={onDeleteByName}
        compact
      />
    </span>
  );
}

export default function EventCalendar({
  events,
  onDeleteById,
  onDeleteByName,
  focusDate,
  onFocusDateChange,
}) {
  const calendarEvents = useMemo(() => toCalendarEvents(events), [events]);

  const components = useMemo(
    () => ({
      event: (props) => (
        <EventCell {...props} onDeleteById={onDeleteById} onDeleteByName={onDeleteByName} />
      ),
    }),
    [onDeleteById, onDeleteByName]
  );

  return (
    <div className="event-calendar">
      <Calendar
        localizer={localizer}
        events={calendarEvents}
        startAccessor="start"
        endAccessor="end"
        views={["month"]}
        defaultView="month"
        date={focusDate}
        onNavigate={onFocusDateChange}
        popup
        components={components}
        style={{ height: 700 }}
      />
    </div>
  );
}
