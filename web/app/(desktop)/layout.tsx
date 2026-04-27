export default function DesktopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-shell">
      <header className="site-header">
        <a href="/" className="brand-lockup">
          <span className="brand-mark">Shorelife</span>
          <span className="brand-subtitle">California beach health forecasts</span>
        </a>
        <nav className="site-nav">
          <a href="/">Forecast</a>
          <a href="/research">Research</a>
          <a href="/methodology">Methodology</a>
        </nav>
      </header>
      {children}
    </div>
  );
}
