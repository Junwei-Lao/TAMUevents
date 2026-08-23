import { useState } from "react";
import Header from "./components/Header.jsx";
import FilterDrawer from "./components/FilterDrawer.jsx";
import EventList from "./components/EventList.jsx";
import { searchEvents } from "./api.js";
import { ALL_VALUE, DEFAULT_FILTERS } from "./filterOptions.js";

function toIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// event_type is a single string on the Event schema; topics/categories/
// categories_audience are arrays - so a chosen dropdown value is sent as a
// bare string for the former and wrapped in a single-element array for the
// latter. "All" means "don't filter on this field", so it's omitted.
function buildRequestBody(range, filters) {
  const body = {
    start_date: toIsoDate(range.from),
    end_date: toIsoDate(range.to),
  };
  for (const [key, value] of Object.entries(filters)) {
    if (value === ALL_VALUE) continue;
    body[key] = key === "event_type" ? value : [value];
  }
  return body;
}

export default function App() {
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [pendingRange, setPendingRange] = useState(undefined);
  const [pendingFilters, setPendingFilters] = useState(DEFAULT_FILTERS);
  const [events, setEvents] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const openDrawer = () => setIsDrawerOpen(true);
  const closeDrawer = () => setIsDrawerOpen(false);

  const updateFilter = (key, value) =>
    setPendingFilters((prev) => ({ ...prev, [key]: value }));

  const clearSelection = () => {
    setPendingRange(undefined);
    setPendingFilters(DEFAULT_FILTERS);
  };

  const applyFilter = async () => {
    if (!pendingRange?.from || !pendingRange?.to) return;
    setIsLoading(true);
    setError(null);
    try {
      const results = await searchEvents(
        buildRequestBody(pendingRange, pendingFilters)
      );
      setEvents(results);
      setIsDrawerOpen(false);
    } catch (err) {
      setError(err.message || "Something went wrong while loading events.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Header onMenuClick={openDrawer} />
      <FilterDrawer
        isOpen={isDrawerOpen}
        range={pendingRange}
        onRangeChange={setPendingRange}
        filters={pendingFilters}
        onFilterChange={updateFilter}
        onClear={clearSelection}
        onApply={applyFilter}
        onClose={closeDrawer}
        isLoading={isLoading}
      />
      <main className="main-content">
        <EventList events={events} isLoading={isLoading} error={error} />
      </main>
    </div>
  );
}
