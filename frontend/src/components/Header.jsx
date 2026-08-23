export default function Header({ onMenuClick }) {
  return (
    <header className="header">
      <button
        className="hamburger-btn"
        aria-label="Open date range filter"
        onClick={onMenuClick}
      >
        <span />
        <span />
        <span />
      </button>
      <h1 className="header-title">TAMU Events</h1>
    </header>
  );
}
