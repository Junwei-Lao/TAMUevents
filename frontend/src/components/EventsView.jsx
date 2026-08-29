import EventList from "./EventList.jsx";
import EventCalendar from "./EventCalendar.jsx";

export default function EventsView({
  events,
  isLoading,
  error,
  viewMode,
  onDeleteById,
  onDeleteByName,
  calendarFocusDate,
  onCalendarFocusDateChange,
}) {
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

  if (viewMode === "calendar") {
    return (
      <EventCalendar
        events={events}
        onDeleteById={onDeleteById}
        onDeleteByName={onDeleteByName}
        focusDate={calendarFocusDate}
        onFocusDateChange={onCalendarFocusDateChange}
      />
    );
  }

  return <EventList events={events} onDeleteById={onDeleteById} onDeleteByName={onDeleteByName} />;
}
