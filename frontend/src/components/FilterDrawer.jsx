import { DayPicker } from "react-day-picker";
import { FILTER_FIELDS } from "../filterOptions.js";

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

function FilterSelect({ field, value, onChange }) {
  return (
    <label className="filter-select">
      <span className="filter-select-label">{field.label}</span>
      <select
        value={value}
        onChange={(e) => onChange(field.key, e.target.value)}
      >
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
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
          <h3 className="drawer-section-title">Filters</h3>
          {FILTER_FIELDS.map((field) => (
            <FilterSelect
              key={field.key}
              field={field}
              value={filters[field.key]}
              onChange={onFilterChange}
            />
          ))}
        </div>

        <div className="drawer-actions">
          <button className="btn btn-secondary" onClick={onClear} disabled={isLoading}>
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
