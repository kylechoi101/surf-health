// Shared styles + utility components for Surf Health
// Weather-app aesthetic: dense, glanceable, clean

const SH_STYLE = `
  .sh-app { font-family: -apple-system, 'SF Pro Text', system-ui, sans-serif;
    color: var(--sh-text); background: var(--sh-bg); -webkit-font-smoothing: antialiased;
    letter-spacing: -0.01em;
  }
  .sh-app * { box-sizing: border-box; }
  .sh-app h1, .sh-app h2, .sh-app h3, .sh-app h4 { margin: 0; font-family: -apple-system, 'SF Pro Display', system-ui, sans-serif; letter-spacing: -0.02em; }

  /* Risk tokens — shared across views */
  .sh-risk-low    { --risk: #22c55e; --risk-bg: #dcfce7; --risk-deep: #15803d; }
  .sh-risk-mod    { --risk: #f59e0b; --risk-bg: #fef3c7; --risk-deep: #b45309; }
  .sh-risk-high   { --risk: #f97316; --risk-bg: #ffedd5; --risk-deep: #c2410c; }
  .sh-risk-vh     { --risk: #ef4444; --risk-bg: #fee2e2; --risk-deep: #b91c1c; }

  /* Dark-mode risk (the main "can I swim" hero sits on risk color) */
  .sh-risk-low  .sh-hero-wash    { background: linear-gradient(170deg, #10b981 0%, #047857 100%); }
  .sh-risk-mod  .sh-hero-wash    { background: linear-gradient(170deg, #f59e0b 0%, #b45309 100%); }
  .sh-risk-high .sh-hero-wash    { background: linear-gradient(170deg, #fb923c 0%, #c2410c 100%); }
  .sh-risk-vh   .sh-hero-wash    { background: linear-gradient(170deg, #f87171 0%, #991b1b 100%); }

  /* Chip / pill */
  .sh-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px;
    border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: 0.01em;
    background: var(--risk-bg); color: var(--risk-deep); }
  .sh-chip.dark { background: rgba(255,255,255,0.22); color: #fff; backdrop-filter: blur(8px); }
  .sh-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--risk); }

  .sh-section-title { font-size: 13px; font-weight: 600; color: var(--sh-muted);
    text-transform: uppercase; letter-spacing: 0.06em; margin: 0 0 10px; padding: 0 20px; }

  /* Generic card */
  .sh-card { background: var(--sh-surface); border-radius: 18px; padding: 14px;
    border: 1px solid var(--sh-border); }

  /* Tab bar */
  .sh-tabbar { display: flex; justify-content: space-around; align-items: flex-start;
    padding: 8px 0 22px; background: var(--sh-tab-bg); backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px); border-top: 1px solid var(--sh-border);
    position: absolute; bottom: 0; left: 0; right: 0; }
  .sh-tab { flex: 1; display: flex; flex-direction: column; align-items: center;
    gap: 3px; padding: 6px 0; color: var(--sh-muted); cursor: pointer;
    background: none; border: none; font-family: inherit; font-size: 10px; font-weight: 600; }
  .sh-tab.active { color: var(--sh-accent); }
`;

function injectShStyle() {
  if (!document.getElementById('sh-style')) {
    const s = document.createElement('style');
    s.id = 'sh-style'; s.textContent = SH_STYLE; document.head.appendChild(s);
  }
}

// ─── Icons (outlined line icons, 24x24) ────────────────────────────────────
const Icon = {
  location: (p) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" {...p}><path d="M12 21s-7-7.5-7-12a7 7 0 1 1 14 0c0 4.5-7 12-7 12Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/><circle cx="12" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.8"/></svg>,
  search: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.8"/><path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  waves: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><path d="M2 10c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  wind: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><path d="M3 8h10a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h9a3 3 0 1 1-3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  sun: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  thermo: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><path d="M10 3.5a2 2 0 0 1 4 0v10.2a4 4 0 1 1-4 0V3.5Z" stroke="currentColor" strokeWidth="1.8"/><circle cx="12" cy="17" r="1.5" fill="currentColor"/></svg>,
  drop: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><path d="M12 3s6 7 6 11a6 6 0 1 1-12 0c0-4 6-11 6-11Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg>,
  tide: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><path d="M3 17h18M3 12c2 0 3-3 5-3s3 3 5 3 3-3 5-3 3 3 3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/><path d="M8 20l2-2M14 20l2-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" opacity="0.5"/></svg>,
  people: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><circle cx="9" cy="8" r="3" stroke="currentColor" strokeWidth="1.8"/><circle cx="17" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.8"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M15 20c0-2 2-4 4-4s3 2 3 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  chevron: (p) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" {...p}><path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  back: (p) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" {...p}><path d="m15 6-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  star: (p) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" {...p}><path d="m12 3 2.7 5.7 6.3.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.3-.9L12 3Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg>,
  starFilled: (p) => <svg width="20" height="20" viewBox="0 0 24 24" {...p}><path d="m12 3 2.7 5.7 6.3.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.3-.9L12 3Z" fill="currentColor"/></svg>,
  map: (p) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" {...p}><path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z M9 4v14M15 6v14" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg>,
  home: (p) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" {...p}><path d="M4 10 12 3l8 7v10a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1V10Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg>,
  profile: (p) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" {...p}><circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.8"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  close: (p) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" {...p}><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>,
  locate: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" {...p}><circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8"/><circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>,
  flask: (p) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" {...p}><path d="M9 3h6M10 3v7l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg>,
};

// Beach risk helpers
function riskClass(band) {
  const m = { 'Low': 'sh-risk-low', 'Moderate': 'sh-risk-mod', 'High': 'sh-risk-high', 'Very High': 'sh-risk-vh' };
  return m[band] || 'sh-risk-mod';
}

// Tiny SVG placeholder "photo" — abstract waves so we don't rely on missing images
function BeachArt({ band, seed = 0, style = {} }) {
  const grads = {
    'Low': ['#60a5fa', '#22c55e', '#fef3c7'],
    'Moderate': ['#f59e0b', '#fbbf24', '#fef3c7'],
    'High': ['#fb923c', '#ef4444', '#fde68a'],
    'Very High': ['#991b1b', '#ef4444', '#fbbf24'],
  };
  const [a, b, c] = grads[band] || grads['Low'];
  const id = `bg-${seed}`;
  return (
    <svg viewBox="0 0 200 100" preserveAspectRatio="xMidYMid slice" style={{ width: '100%', height: '100%', display: 'block', ...style }}>
      <defs>
        <linearGradient id={id} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={a}/>
          <stop offset="60%" stopColor={b}/>
          <stop offset="100%" stopColor={c}/>
        </linearGradient>
      </defs>
      <rect width="200" height="100" fill={`url(#${id})`}/>
      <circle cx={160 + (seed % 3) * 5} cy={22} r="10" fill="#fff" opacity="0.35"/>
      <path d={`M0 ${70 + (seed%3)} C 40 ${62 + seed%4}, 80 ${78 - seed%3}, 120 ${70 + seed%4} S 180 ${66 + seed%3}, 220 ${72}`} stroke="#fff" strokeWidth="1.2" fill="none" opacity="0.5"/>
      <path d={`M0 ${82} C 40 ${76}, 80 ${88}, 120 ${82} S 180 ${78}, 220 ${84}`} stroke="#fff" strokeWidth="1" fill="none" opacity="0.35"/>
      <path d={`M0 ${100} L0 ${92} C 40 ${88}, 80 ${96}, 120 ${92} S 180 ${88}, 220 ${94} L220 ${100} Z`} fill="#f5e6b8" opacity="0.7"/>
    </svg>
  );
}

Object.assign(window, { injectShStyle, Icon, riskClass, BeachArt });
