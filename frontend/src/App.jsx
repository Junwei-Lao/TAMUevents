import { useEffect, useMemo, useState } from "react";
import Header from "./components/Header.jsx";
import FilterDrawer from "./components/FilterDrawer.jsx";
import SettingsDrawer from "./components/SettingsDrawer.jsx";
import EventsView from "./components/EventsView.jsx";
import AnnouncementPanel from "./components/AnnouncementPanel.jsx";
import Footer from "./components/Footer.jsx";
import { searchEvents } from "./api.js";
import { DEFAULT_FILTERS } from "./filterOptions.js";
import { dedupeEventsByUrl, excludeBlacklistedEvents } from "./eventFilters.js";
import { EVENT_NAME_BLACKLIST } from "./eventNameBlacklist.js";
import { useLocalStorageState } from "./hooks/useLocalStorageState.js";
import { applyTheme, DEFAULT_THEME_KEY } from "./themes.js";
import { parseIsoDateLocal } from "./dateUtils.js";
import { getLatestAnnouncement } from "./announcements.js";

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
//
// The contract's event_type field is shaped like topic_taxomony
// ({parent: [leaf, ...]}), but backend.py only ever reads its keys - event
// types are stored per-Event at the parent-category level only (see
// filterOptions.js) - so the UI just picks flat parent names and this
// wraps each one in an (unused) empty leaf array to match the shape.
function buildRequestBody(range, filters) {
  const eventType = Object.fromEntries(filters.event_type.map((parent) => [parent, []]));

  return {
    start_date: toIsoDate(range.from),
    end_date: toIsoDate(range.to),
    topic_taxomony: filters.topics,
    event_type: eventType,
    categories: filters.categories,
    categories_audience: filters.categories_audience,
  };
}

export default function App() {
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [pendingRange, setPendingRange] = useState(undefined);
  const [pendingFilters, setPendingFilters] = useState(DEFAULT_FILTERS);
  // The raw (deduped + code-blacklisted) results of the last search - not
  // itself shown directly, see visibleEvents below.
  const [rawEvents, setRawEvents] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  // Which month the calendar view is showing. Reset to the earliest result
  // whenever a new search completes (see applyFilter) so switching to
  // Calendar right after applying a future date range doesn't land on an
  // empty "today" month; left alone otherwise (e.g. deleting/restoring an
  // event, or the user manually paging the calendar) so it doesn't jump
  // around from actions unrelated to running a new search.
  const [calendarFocusDate, setCalendarFocusDate] = useState(new Date());

  // Settings persist across a refresh (unlike rawEvents/pendingRange/
  // pendingFilters above, which intentionally reset - see README).
  const [themeKey, setThemeKey] = useLocalStorageState("themeKey", DEFAULT_THEME_KEY);
  const [viewMode, setViewMode] = useLocalStorageState("viewMode", "list");
  const [deletedEventUrls, setDeletedEventUrls] = useLocalStorageState("deletedEventUrls", []);
  const [deletedEventNames, setDeletedEventNames] = useLocalStorageState("deletedEventNames", []);

  // The newest file in src/announcement/, and whether the user has
  // permanently dismissed it ("never show again"). Comparing by id (the
  // file path) rather than a single "dismissed" boolean means a future
  // announcement file always shows once, even if an older one was
  // dismissed for good.
  const [dismissedAnnouncementId, setDismissedAnnouncementId] = useLocalStorageState(
    "dismissedAnnouncementId",
    null
  );
  const latestAnnouncement = useMemo(() => getLatestAnnouncement(), []);
  const [isAnnouncementVisible, setIsAnnouncementVisible] = useState(
    () => Boolean(latestAnnouncement) && latestAnnouncement.id !== dismissedAnnouncementId
  );

  const confirmAnnouncement = (neverShowAgain) => {
    if (neverShowAgain && latestAnnouncement) {
      setDismissedAnnouncementId(latestAnnouncement.id);
    }
    setIsAnnouncementVisible(false);
  };

  useEffect(() => applyTheme(themeKey), [themeKey]);

  // Deletions/restores apply live against whatever was last fetched, so
  // toggling them in Settings updates the main page immediately without
  // needing to re-run the search.
  const visibleEvents = useMemo(() => {
    const deletedUrls = new Set(deletedEventUrls.map((entry) => entry.url));
    const deletedNames = new Set(deletedEventNames.map((name) => name.toLowerCase()));
    return rawEvents.filter(
      (event) =>
        !deletedUrls.has(event.url) &&
        !deletedNames.has((event.title || "").toLowerCase())
    );
  }, [rawEvents, deletedEventUrls, deletedEventNames]);

  const openDrawer = () => setIsDrawerOpen(true);
  const closeDrawer = () => setIsDrawerOpen(false);
  const openSettings = () => setIsSettingsOpen(true);
  const closeSettings = () => setIsSettingsOpen(false);

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
      const deduped = dedupeEventsByUrl(results);
      const finalResults = excludeBlacklistedEvents(deduped, EVENT_NAME_BLACKLIST);
      setRawEvents(finalResults);

      const earliestStartDate = finalResults
        .map((event) => event.start_date)
        .filter(Boolean)
        .sort()[0];
      if (earliestStartDate) setCalendarFocusDate(parseIsoDateLocal(earliestStartDate));

      setIsDrawerOpen(false);
    } catch (err) {
      setError(err.message || "Something went wrong while loading events.");
    } finally {
      setIsLoading(false);
    }
  };

  const deleteEventByUrl = (event) => {
    setDeletedEventUrls((prev) =>
      prev.some((entry) => entry.url === event.url)
        ? prev
        : [...prev, { url: event.url, title: event.title, date: event.date }]
    );
  };

  const deleteEventsByName = (event) => {
    setDeletedEventNames((prev) => (prev.includes(event.title) ? prev : [...prev, event.title]));
  };

  const restoreEventByUrl = (url) => {
    setDeletedEventUrls((prev) => prev.filter((entry) => entry.url !== url));
  };

  const restoreEventByName = (name) => {
    setDeletedEventNames((prev) => prev.filter((n) => n !== name));
  };

  return (
    <div className="app">
      {isAnnouncementVisible && latestAnnouncement && (
        <AnnouncementPanel announcement={latestAnnouncement} onConfirm={confirmAnnouncement} />
      )}
      <Header onMenuClick={openDrawer} onSettingsClick={openSettings} />
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
      <SettingsDrawer
        isOpen={isSettingsOpen}
        onClose={closeSettings}
        themeKey={themeKey}
        onThemeChange={setThemeKey}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        deletedEventUrls={deletedEventUrls}
        deletedEventNames={deletedEventNames}
        onRestoreByUrl={restoreEventByUrl}
        onRestoreByName={restoreEventByName}
      />
      <main className={`main-content ${viewMode === "calendar" ? "main-content--calendar" : ""}`}>
        <EventsView
          events={visibleEvents}
          isLoading={isLoading}
          error={error}
          viewMode={viewMode}
          onDeleteByUrl={deleteEventByUrl}
          onDeleteByName={deleteEventsByName}
          calendarFocusDate={calendarFocusDate}
          onCalendarFocusDateChange={setCalendarFocusDate}
        />
      </main>
      <Footer />
    </div>
  );
}
