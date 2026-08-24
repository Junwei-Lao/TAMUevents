import { useState } from "react";
import Header from "./components/Header.jsx";
import FilterDrawer from "./components/FilterDrawer.jsx";
import EventList from "./components/EventList.jsx";
import Footer from "./components/Footer.jsx";
import { searchEvents } from "./api.js";
import { DEFAULT_FILTERS } from "./filterOptions.js";
import {
  TOPIC_TAXONOMY,
  EVENT_TYPE_TAXONOMY,
  CATEGORY_OPTIONS,
  AUDIENCE_OPTIONS,
} from "./taxonomy.js";

function toIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// docs/front_back_contract.md: a section with no explicit picks means "All"
// - and "All" is sent as every value that section could ever hold, rather
// than an omitted/empty field, since the contract always expects the field
// present.
function buildRequestBody(range, filters) {
  const topicTaxomony =
    Object.keys(filters.topics).length > 0 ? filters.topics : TOPIC_TAXONOMY;
  const eventType =
    Object.keys(filters.event_type).length > 0 ? filters.event_type : EVENT_TYPE_TAXONOMY;
  const categories =
    filters.categories.length > 0 ? filters.categories : CATEGORY_OPTIONS;
  const categoriesAudience =
    filters.categories_audience.length > 0
      ? filters.categories_audience
      : AUDIENCE_OPTIONS;

  return {
    start_date: toIsoDate(range.from),
    end_date: toIsoDate(range.to),
    topic_taxomony: topicTaxomony,
    event_type: eventType,
    categories,
    categories_audience: categoriesAudience,
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
