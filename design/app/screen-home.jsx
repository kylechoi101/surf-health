// Home screen — "Can I swim?" hero + nearby list
// The big single answer is the whole point. Everything else is context.

function HomeScreen({ beach, onOpenBeach, onOpenMap, onOpenSearch, nearby }) {
  const meta = window.RISK_META[beach.risk];
  const hourly = [
    { h: 'Now', v: beach.waveFt },
    { h: '10a', v: beach.waveFt + 0.2 },
    { h: '12p', v: beach.waveFt + 0.4 },
    { h: '2p', v: beach.waveFt + 0.1 },
    { h: '4p', v: beach.waveFt - 0.2 },
    { h: '6p', v: beach.waveFt - 0.4 },
    { h: '8p', v: beach.waveFt - 0.3 },
  ];
  const peak = Math.max(...hourly.map(p => p.v));

  return (
    <div className={`sh-app ${riskClass(beach.risk)}`}
      style={{ '--sh-bg': '#f2f4f7', '--sh-text': '#0f172a', '--sh-muted': '#64748b',
        '--sh-surface': '#fff', '--sh-border': '#e5e7eb', '--sh-accent': '#0b4266',
        '--sh-tab-bg': 'rgba(255,255,255,0.92)',
        height: '100%', overflowY: 'auto', paddingBottom: 90 }}>

      {/* HERO — big answer */}
      <div className="sh-hero-wash"
        style={{ color: '#fff', padding: '8px 20px 24px', position: 'relative', overflow: 'hidden' }}>
        {/* subtle sun + wave texture */}
        <svg viewBox="0 0 400 280" preserveAspectRatio="none"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.25, pointerEvents: 'none' }}>
          <circle cx="340" cy="50" r="46" fill="#fff"/>
          <path d="M0 220 C 80 210, 160 240, 240 220 S 400 210, 400 220 L400 280 L0 280 Z" fill="#fff" opacity="0.12"/>
          <path d="M0 240 C 80 230, 160 260, 240 240 S 400 230, 400 240" stroke="#fff" strokeWidth="1" fill="none" opacity="0.4"/>
        </svg>
        <div style={{ position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 16 }}>
            <Icon.location style={{ width: 16, height: 16 }}/>
            <button onClick={onOpenSearch} style={{ background: 'none', border: 'none', color: '#fff',
              fontFamily: 'inherit', fontSize: 14, fontWeight: 600, padding: 0, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 4 }}>
              {beach.name} <Icon.chevron style={{ width: 14, height: 14, opacity: 0.7 }}/>
            </button>
            <span style={{ marginLeft: 'auto', fontSize: 11, opacity: 0.8 }}>Updated 5:02 AM</span>
          </div>
          <div style={{ marginTop: 28 }}>
            <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.08em',
              textTransform: 'uppercase', opacity: 0.85 }}>Can I swim today?</div>
            <h1 style={{ fontSize: 58, lineHeight: 0.95, fontWeight: 700, marginTop: 6 }}>
              {beach.risk === 'Low' ? 'Yes.' : beach.risk === 'Moderate' ? 'Maybe.' : beach.risk === 'High' ? 'Not ideal.' : 'Avoid.'}
            </h1>
            <p style={{ fontSize: 15, marginTop: 10, lineHeight: 1.45, maxWidth: 320, opacity: 0.95 }}>
              {meta.advice}
            </p>
          </div>

          {/* quick stat row */}
          <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
            <Stat icon={<Icon.flask/>} label="Bacteria" value={`${Math.round(beach.p*100)}%`} sub="exceed chance"/>
            <Stat icon={<Icon.waves/>} label="Surf" value={`${beach.waveFt}ft`} sub={`${beach.period}s period`}/>
            <Stat icon={<Icon.thermo/>} label="Water" value={`${beach.temp}°`} sub={`${beach.wind} mph wind`}/>
          </div>

          <button onClick={() => onOpenBeach && onOpenBeach(beach)}
            style={{ width: '100%', marginTop: 20, padding: '14px', border: 'none',
              borderRadius: 14, background: 'rgba(255,255,255,0.22)', backdropFilter: 'blur(8px)',
              color: '#fff', fontFamily: 'inherit', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
            See what's driving this forecast →
          </button>
        </div>
      </div>

      {/* Hourly surf */}
      <div style={{ padding: '22px 0 0' }}>
        <div className="sh-section-title">Surf today</div>
        <div style={{ margin: '0 20px', padding: 16, background: '#fff', borderRadius: 18, border: '1px solid #e5e7eb' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', height: 70, gap: 4 }}>
            {hourly.map((h, i) => {
              const pct = (h.v / peak) * 100;
              return (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, height: '100%', justifyContent: 'flex-end' }}>
                  <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>{h.v.toFixed(1)}</div>
                  <div style={{ width: '100%', height: `${pct}%`, minHeight: 4,
                    background: `linear-gradient(180deg, #0ea5e9, #0b4266)`,
                    borderRadius: 5, opacity: i === 2 ? 1 : 0.75 }}/>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
            {hourly.map((h, i) => <div key={i} style={{ fontSize: 10, color: '#94a3b8', flex: 1, textAlign: 'center', fontWeight: 600 }}>{h.h}</div>)}
          </div>
        </div>
      </div>

      {/* Nearby beaches */}
      <div style={{ padding: '24px 0 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '0 20px', marginBottom: 10 }}>
          <div className="sh-section-title" style={{ padding: 0, margin: 0 }}>Nearby</div>
          <button onClick={onOpenMap} style={{ background: 'none', border: 'none',
            color: '#0b4266', fontFamily: 'inherit', fontSize: 13, fontWeight: 600, cursor: 'pointer', padding: 0 }}>
            View map →
          </button>
        </div>
        <div style={{ padding: '0 20px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {nearby.slice(0, 5).map((b, i) => {
            const bm = window.RISK_META[b.risk];
            return (
              <button key={b.id} onClick={() => onOpenBeach && onOpenBeach(b)}
                className={riskClass(b.risk)}
                style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
                  background: '#fff', border: '1px solid #e5e7eb', borderRadius: 14, cursor: 'pointer',
                  fontFamily: 'inherit', textAlign: 'left', width: '100%' }}>
                <div style={{ width: 44, height: 44, borderRadius: 11, overflow: 'hidden', flexShrink: 0 }}>
                  <BeachArt band={b.risk} seed={i}/>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {b.waveFt}ft · {b.temp}° · {b.crowd}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5,
                    padding: '4px 8px', borderRadius: 999, background: 'var(--risk-bg)', color: 'var(--risk-deep)',
                    fontSize: 11, fontWeight: 700 }}>
                    <span className="sh-dot"/>{b.risk}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <TabBar current="home" onOpenMap={onOpenMap} onOpenSearch={onOpenSearch}/>
    </div>
  );
}

function Stat({ icon, label, value, sub }) {
  return (
    <div style={{ flex: 1, padding: '10px 12px', background: 'rgba(255,255,255,0.18)',
      borderRadius: 14, backdropFilter: 'blur(8px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, opacity: 0.85 }}>
        {icon}<span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
      <div style={{ fontSize: 10, opacity: 0.8, marginTop: 2 }}>{sub}</div>
    </div>
  );
}

function TabBar({ current, onOpenMap, onOpenSearch, onOpenHome, onOpenProfile }) {
  const tabs = [
    { id: 'home', label: 'Today', icon: Icon.home, on: onOpenHome },
    { id: 'map', label: 'Map', icon: Icon.map, on: onOpenMap },
    { id: 'search', label: 'Search', icon: Icon.search, on: onOpenSearch },
    { id: 'profile', label: 'You', icon: Icon.profile, on: onOpenProfile },
  ];
  return (
    <div className="sh-tabbar">
      {tabs.map(t => (
        <button key={t.id} className={`sh-tab ${current === t.id ? 'active' : ''}`}
          onClick={t.on}>
          {React.createElement(t.icon, { style: { width: 22, height: 22 } })}
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  );
}

Object.assign(window, { HomeScreen, TabBar });
