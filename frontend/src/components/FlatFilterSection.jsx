import { ALL_LABEL } from "../filterOptions.js";

// Renders a flat (no parent/leaf grouping) multi-select chip filter, used
// for categories / categories_audience - those are discovered pools, not a
// fixed taxonomy, so there's nothing to nest.
export default function FlatFilterSection({ title, options, selected, onToggle, onSelectAll }) {
  const isAll = selected.length === 0;

  return (
    <div className="filter-section">
      <h3 className="drawer-section-title">{title}</h3>
      <div className="chip-row">
        <button
          type="button"
          className={`chip ${isAll ? "chip--active" : ""}`}
          onClick={onSelectAll}
        >
          {ALL_LABEL}
        </button>
        {options.map((option) => {
          const isSelected = selected.includes(option);
          return (
            <button
              type="button"
              key={option}
              className={`chip ${isSelected ? "chip--active" : ""}`}
              onClick={() => onToggle(option)}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}
