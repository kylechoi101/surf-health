// Map view — 50+ beach pins over a stylized California coastline

function MapScreen({ beaches, onPick, onBack, mapStyle = 'dark' }) {
  const [selected, setSelected] = React.useState(null);
  const [filter, setFilter] = React.useState('all');

  // project lat/lon -> x/y (matches the coastline path below)
  // CA lat 32.4–41.9, lon -124.5 to -117.0
  const project = (lat, lon) => {
    const x = ((lon + 124.5) / 7.5) * 100;
    const y = 100 - ((lat - 32.4) / 9.5) * 100;
    return { x, y };
  };

  const filtered = filter === 'all' ? beaches
    : filter === 'safe' ? beaches.filter(b => b.risk === 'Low')
    : filter === 'avoid' ? beaches.filter(b => b.risk === 'High' || b.risk === 'Very High')
    : beaches;

  const palette = mapStyle === 'light'
    ? { bg: '#e3eef5', land: '#f1f5f9', landStroke: '#cbd5e1', label: '#334155', text: '#0f172a', sheet: '#fff' }
    : { bg: '#0b1a28', land: '#0f2b3f', landStroke: '#1d4560', label: 'rgba(255,255,255,0.35)', text: '#fff', sheet: '#0f2b3f' };

  const selBeach = selected && beaches.find(b => b.id === selected);

  return (
    <div className="sh-app" style={{ height: '100%', position: 'relative',
      background: palette.bg, color: palette.text, overflow: 'hidden' }}>

      {/* MAP */}
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        <defs>
          <pattern id="mapgrid" width="6" height="6" patternUnits="userSpaceOnUse">
            <path d="M6 0H0V6" fill="none" stroke={mapStyle==='light'?'#d4dfe7':'#12243a'} strokeWidth="0.15"/>
          </pattern>
        </defs>
        <rect width="100" height="100" fill="url(#mapgrid)"/>

        {/* California coastline silhouette — stylized */}
        <path d="M 18 2 L 22 6 L 21 9 L 23 13 L 22 18 L 25 22 L 24 27 L 26 33 L 24 38 L 27 42 L 26 48 L 29 53 L 28 58 L 31 63 L 30 68 L 33 73 L 35 78 L 38 82 L 43 85 L 48 88 L 55 91 L 62 94 L 70 96 L 80 97 L 90 98 L 100 98 L 100 100 L 0 100 L 0 0 L 18 0 Z"
          fill={palette.land} stroke={palette.landStroke} strokeWidth="0.3"/>

        {/* County labels */}
        <g fontSize="2.5" fill={palette.label} fontFamily="-apple-system, sans-serif" fontWeight="600" letterSpacing="0.3">
          <text x="8" y="18">NORCAL</text>
          <text x="12" y="48">CENTRAL</text>
          <text x="40" y="85">SOCAL</text>
        </g>

        {/* Beach pins */}
        {filtered.map((b, i) => {
          const { x, y } = project(b.lat, b.lon);
          const meta = window.RISK_META[b.risk];
          const isSel = selected === b.id;
          return (
            <g key={b.id} style={{ cursor: 'pointer' }} onClick={() => setSelected(b.id)}>
              {isSel && <circle cx={x} cy={y} r="3.5" fill={meta.dot} opacity="0.25"/>}
              <circle cx={x} cy={y} r={isSel ? 1.8 : 1.3} fill={meta.dot}
                stroke="#fff" strokeWidth="0.35"/>
            </g>
          );
        })}
      </svg>

      {/* TOP BAR */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0,
        padding: '12px 16px 16px', display: 'flex', gap: 10,
        background: `linear-gradient(180deg, ${mapStyle==='light'?'rgba(227,238,245,1)':'rgba(11,26,40,1)'} 0%, transparent 100%)` }}>
        <button onClick={onBack} style={{ width: 38, height: 38, borderRadius: 12,
          background: palette.sheet, border: 'none', color: palette.text,
          display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          boxShadow: '0 2px 10px rgba(0,0,0,0.15)' }}>
          <Icon.back/>
        </button>
        <div style={{ flex: 1, background: palette.sheet, borderRadius: 12,
          display: 'flex', alignItems: 'center', gap: 10, padding: '0 14px',
          color: palette.text, boxShadow: '0 2px 10px rgba(0,0,0,0.15)' }}>
          <Icon.search style={{ opacity: 0.6 }}/>
          <span style={{ fontSize: 14, opacity: 0.7 }}>Search California coast</span>
        </div>
        <button style={{ width: 38, height: 38, borderRadius: 12,
          background: palette.sheet, border: 'none', color: palette.text,
          display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          boxShadow: '0 2px 10px rgba(0,0,0,0.15)' }}>
          <Icon.locate/>
        </button>
      </div>

      {/* FILTER CHIPS */}
      <div style={{ position: 'absolute', top: 68, left: 16, right: 16, display: 'flex', gap: 8, overflowX: 'auto' }}>
        {[
          { id: 'all', label: `All ${beaches.length}`, color: mapStyle==='light'?'#0f172a':'#fff' },
          { id: 'safe', label: 'Safe to swim', color: '#22c55e' },
          { id: 'avoid', label: 'Avoid', color: '#ef4444' },
          { id: 'fav', label: '★ Favorites', color: '#f59e0b' },
        ].map(c => (
          <button key={c.id} onClick={() => setFilter(c.id)}
            style={{ padding: '7px 12px', borderRadius: 999, border: 'none',
              background: filter === c.id ? c.color : palette.sheet,
              color: filter === c.id ? '#fff' : palette.text,
              fontSize: 12, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
              whiteSpace: 'nowrap', boxShadow: '0 2px 8px rgba(0,0,0,0.12)' }}>
            {c.label}
          </button>
        ))}
      </div>

      {/* Legend */}
      <div style={{ position: 'absolute', right: 16, bottom: selBeach ? 230 : 30,
        padding: '10px 12px', background: palette.sheet, borderRadius: 12,
        boxShadow: '0 4px 14px rgba(0,0,0,0.15)', transition: 'bottom 200ms' }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
          textTransform: 'uppercase', opacity: 0.6, marginBottom: 6 }}>Risk</div>
        {['Low','Moderate','High','Very High'].map(r => (
          <div key={r} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, marginTop: 3 }}>
            <span style={{ width: 8, height: 8, borderRadius: 4, background: window.RISK_META[r].dot }}/>
            {r}
          </div>
        ))}
      </div>

      {/* Selected beach bottom sheet */}
      {selBeach && (
        <div className={riskClass(selBeach.risk)}
          style={{ position: 'absolute', left: 12, right: 12, bottom: 18,
            background: palette.sheet, color: palette.text, borderRadius: 20, padding: 16,
            boxShadow: '0 16px 40px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, overflow: 'hidden', flexShrink: 0 }}>
              <BeachArt band={selBeach.risk} seed={selBeach.lat}/>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 17, fontWeight: 700 }}>{selBeach.name}</div>
              <div style={{ fontSize: 12, opacity: 0.65, marginTop: 2 }}>{selBeach.county} County · {selBeach.region}</div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '4px 9px', borderRadius: 999, background: 'var(--risk-bg)',
                color: 'var(--risk-deep)', fontSize: 11, fontWeight: 700, marginTop: 6 }}>
                <span className="sh-dot"/>{selBeach.risk} · {Math.round(selBeach.p*100)}% exceed
              </div>
            </div>
            <button onClick={() => setSelected(null)}
              style={{ background: 'none', border: 'none', color: palette.text, opacity: 0.5, cursor: 'pointer' }}>
              <Icon.close/>
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12, fontSize: 11 }}>
            <MiniStat icon={<Icon.waves/>} v={`${selBeach.waveFt}ft`} l={`${selBeach.period}s`}/>
            <MiniStat icon={<Icon.thermo/>} v={`${selBeach.temp}°`} l="water"/>
            <MiniStat icon={<Icon.wind/>} v={`${selBeach.wind}mph`} l="wind"/>
            <MiniStat icon={<Icon.people/>} v={selBeach.crowd} l="crowd"/>
          </div>
          <button onClick={() => onPick && onPick(selBeach)}
            style={{ width: '100%', marginTop: 12, padding: '12px', borderRadius: 12,
              border: 'none', background: '#0b4266', color: '#fff',
              fontFamily: 'inherit', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
            Open forecast →
          </button>
        </div>
      )}

      {!selBeach && <TabBar current="map" onOpenMap={()=>{}} onOpenHome={onBack}/>}
    </div>
  );
}

function MiniStat({ icon, v, l }) {
  return (
    <div style={{ flex: 1, padding: '8px 6px', background: 'rgba(0,0,0,0.04)',
      borderRadius: 10, textAlign: 'center' }}>
      <div style={{ display: 'flex', justifyContent: 'center', opacity: 0.7 }}>{icon}</div>
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2 }}>{v}</div>
      <div style={{ fontSize: 9, opacity: 0.55, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{l}</div>
    </div>
  );
}

Object.assign(window, { MapScreen });
