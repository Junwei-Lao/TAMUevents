import { useState } from "react";
import Header from "./components/Header.jsx";
import FilterDrawer from "./components/FilterDrawer.jsx";
import EventList from "./components/EventList.jsx";
import Footer from "./components/Footer.jsx";
import { searchEvents } from "./api.js";
import { DEFAULT_FILTERS } from "./filterOptions.js";

function toIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// backend.py's SearchRequest / postgre_io.search_events (see
// docs/back_db_contract.md) treat an empty dict/array as "no filter on this
// field" - so "All" (no explicit picks) is sent as {} / [] as-is, not
// expanded into every possible value.
function buildRequestBody(range, filters) {
  return {
    start_date: toIsoDate(range.from),
    end_date: toIsoDate(range.to),
    topic_taxomony: filters.topics,
    event_type: filters.event_type,
    categories: filters.categories,
    categories_audience: filters.categories_audience,
  };
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
      <Footer />
    </div>
  );
}
