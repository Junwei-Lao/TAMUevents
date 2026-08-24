import { useState } from "react";
import { DayPicker } from "react-day-picker";
import TaxonomyFilterSection from "./TaxonomyFilterSection.jsx";
import FlatFilterSection from "./FlatFilterSection.jsx";
import { TOPIC_TAXONOMY, EVENT_TYPE_TAXONOMY, CATEGORY_OPTIONS, AUDIENCE_OPTIONS } from "../taxonomy.js";

function formatRangeLabel(range) {
  if (!range?.from) return "No dates selected";
  const fmt = (d) =>
    d.toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  if (!range.to || range.from.getTime() === range.to.getTime()) {
    return fmt(range.from);
  }
  return `${fmt(range.from)} - ${fmt(range.to)}`;
}

function toggleInSet(set, value) {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function toggleTaxonomyLeaf(selected, parent, leaf) {
  const current = selected[parent] || [];
  const nextLeaves = current.includes(leaf)
    ? current.filter((l) => l !== leaf)
    : [...current, leaf];

  const next = { ...selected };
  if (nextLeaves.length === 0) delete next[parent];
  else next[parent] = nextLeaves;
  return next;
}

function toggleAllLeavesForParent(selected, parent, allLeaves) {
  const current = selected[parent] || [];
  const next = { ...selected };
  if (current.length === allLeaves.length) {
    delete next[parent];
  } else {
    next[parent] = [...allLeaves];
  }
  return next;
}

function toggleFlatValue(selected, value) {
  return selected.includes(value)
    ? selected.filter((v) => v !== value)
    : [...selected, value];
}

export default function FilterDrawer({
  isOpen,
  range,
  onRangeChange,
  filters,
  onFilterChange,
  onClear,
  onApply,
  onClose,
  isLoading,
}) {
  const canApply = Boolean(range?.from && range?.to) && !isLoading;

  const [expandedTopics, setExpandedTopics] = useState(new Set());
  const [expandedEventTypes, setExpandedEventTypes] = useState(new Set());

  const handleClear = () => {
    onClear();
    setExpandedTopics(new Set());
    setExpandedEventTypes(new Set());
  };

  return (
    <>
      <div
        className={`drawer-overlay ${isOpen ? "drawer-overlay--open" : ""}`}
        onClick={onClose}
      />
      <aside className={`drawer ${isOpen ? "drawer--open" : ""}`}>
        <div className="drawer-header">
          <h2>Select Date Range</h2>
          <button className="drawer-close-btn" aria-label="Close" onClick={onClose}>
            &times;
          </button>
        </div>

        <p className="drawer-range-label">{formatRangeLabel(range)}</p>

        <DayPicker
          mode="range"
          selected={range}
          onSelect={onRangeChange}
          numberOfMonths={1}
          disabled={{ before: new Date() }}
        />

        <div className="drawer-filters">
          <TaxonomyFilterSection
            title="Topics"
            taxonomy={TOPIC_TAXONOMY}
            selected={filters.topics}
            expandedParents={expandedTopics}
            onToggleExpand={(parent) =>
              setExpandedTopics((prev) => toggleInSet(prev, parent))
            }
            onToggleLeaf={(parent, leaf) =>
              onFilterChange("topics", toggleTaxonomyLeaf(filters.topics, parent, leaf))
            }
            onToggleParentAll={(parent, allLeaves) =>
              onFilterChange("topics", toggleAllLeavesForParent(filters.topics, parent, allLeaves))
            }
            onSelectAll={() => onFilterChange("topics", {})}
          />

          <TaxonomyFilterSection
            title="Event Type"
            taxonomy={EVENT_TYPE_TAXONOMY}
            selected={filters.event_type}
            expandedParents={expandedEventTypes}
            onToggleExpand={(parent) =>
              setExpandedEventTypes((prev) => toggleInSet(prev, parent))
            }
            onToggleLeaf={(parent, leaf) =>
              onFilterChange(
                "event_type",
                toggleTaxonomyLeaf(filters.event_type, parent, leaf)
              )
            }
            onToggleParentAll={(parent, allLeaves) =>
              onFilterChange(
                "event_type",
                toggleAllLeavesForParent(filters.event_type, parent, allLeaves)
              )
            }
            onSelectAll={() => onFilterChange("event_type", {})}
          />

          <FlatFilterSection
            title="Categories"
            options={CATEGORY_OPTIONS}
            selected={filters.categories}
            onToggle={(value) =>
              onFilterChange("categories", toggleFlatValue(filters.categories, value))
            }
            onSelectAll={() => onFilterChange("categories", [])}
          />

          <FlatFilterSection
            title="Audience"
            options={AUDIENCE_OPTIONS}
            selected={filters.categories_audience}
            onToggle={(value) =>
              onFilterChange(
                "categories_audience",
                toggleFlatValue(filters.categories_audience, value)
              )
            }
            onSelectAll={() => onFilterChange("categories_audience", [])}
          />
        </div>

        <div className="drawer-actions">
          <button className="btn btn-secondary" onClick={handleClear} disabled={isLoading}>
            Clear Selection
          </button>
          <button className="btn btn-primary" onClick={onApply} disabled={!canApply}>
            {isLoading ? "Applying..." : "Apply Filter"}
          </button>
        </div>
      </aside>
    </>
  );
}
