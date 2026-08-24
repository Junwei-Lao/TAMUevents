import { ALL_LABEL } from "../filterOptions.js";

// Renders a two-level taxonomy filter: an "All" chip, then one split
// button per parent category - the label half selects every leaf under
// that parent in one press, the separate "+"/"−" half only expands or
// collapses the leaf chips below it (and doesn't change the selection).
// Leaf chips themselves toggle individually. Only leaves are ever sent to
// the backend (grouped back under their parent).
export default function TaxonomyFilterSection({
  title,
  taxonomy,
  selected,
  expandedParents,
  onToggleExpand,
  onToggleLeaf,
  onToggleParentAll,
  onSelectAll,
}) {
  const isAll = Object.keys(selected).length === 0;

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
        {Object.keys(taxonomy).map((parent) => {
          const isExpanded = expandedParents.has(parent);
          const selectedCount = selected[parent]?.length || 0;
          const allSelected = selectedCount === taxonomy[parent].length;
          return (
            <span className="chip-split" key={parent}>
              <button
                type="button"
                className={`chip chip--parent-label ${allSelected ? "chip--active" : ""}`}
                onClick={() => onToggleParentAll(parent, taxonomy[parent])}
                title={`Select all ${parent} topics`}
              >
                {parent}
                {selectedCount > 0 && !allSelected ? ` (${selectedCount})` : ""}
              </button>
              <button
                type="button"
                className={`chip-expand-btn ${isExpanded ? "chip-expand-btn--active" : ""}`}
                onClick={() => onToggleExpand(parent)}
                aria-expanded={isExpanded}
                aria-label={`${isExpanded ? "Collapse" : "Expand"} ${parent}`}
              >
                {isExpanded ? "−" : "+"}
              </button>
            </span>
          );
        })}
      </div>

      {Object.keys(taxonomy)
        .filter((parent) => expandedParents.has(parent))
        .map((parent) => (
          <div className="chip-row chip-row--leaves" key={parent}>
            {taxonomy[parent].map((leaf) => {
              const isSelected = Boolean(selected[parent]?.includes(leaf));
              return (
                <button
                  type="button"
                  key={leaf}
                  className={`chip chip--leaf ${isSelected ? "chip--active" : ""}`}
                  onClick={() => onToggleLeaf(parent, leaf)}
                >
                  {leaf}
                </button>
              );
            })}
          </div>
        ))}
    </div>
  );
}
