// A simple trash-can glyph. `all` overlays a small "ALL" badge at the
// bottom-right corner, for the "delete every event with this name" action.
export default function TrashIcon({ all = false }) {
  return (
    <span className="trash-icon">
      <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
        <path
          fill="currentColor"
          d="M9 3a1 1 0 0 0-1 1v1H4v2h16V5h-4V4a1 1 0 0 0-1-1H9Zm-3 6 1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12H6Z"
        />
      </svg>
      {all && <span className="trash-icon-badge">ALL</span>}
    </span>
  );
}
