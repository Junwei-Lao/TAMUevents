export default function Footer() {
  return (
    <footer className="footer">
      <span>&copy; {new Date().getFullYear()} TAMU Events. All rights reserved.</span>
      <span className="footer-divider">|</span>
      <span>
        Contact us: <a href="mailto:contact@tamuevent.com">contact@tamuevent.com</a>
      </span>
    </footer>
  );
}
