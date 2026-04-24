export default function DesktopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-shell">
      <header className="site-header">
        <a href="/" className="brand-lockup">
          <span className="brand-mark">Surf Health</span>
          <span className="brand-subtitle">California marine bacteria nowcasts</span>
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
