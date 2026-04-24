// Location select / onboarding screen
// Big intro, auto-detect button, manual search, recent + nearby

function LocationSelectScreen({ onPick }) {
  const [q, setQ] = React.useState('');
  const [focused, setFocused] = React.useState(false);
  const beaches = window.BEACHES;
  const results = q ? beaches.filter(b =>
    b.name.toLowerCase().includes(q.toLowerCase()) ||
    b.county.toLowerCase().includes(q.toLowerCase())
  ).slice(0, 8) : [];
  const recent = ['manhattan-beach-pier', 'malibu', 'trestles']
    .map(id => beaches.find(b => b.id === id)).filter(Boolean);

  return (
    <div className="sh-app" style={{ height: '100%', display: 'flex', flexDirection: 'column',
      background: 'linear-gradient(180deg, #0b4266 0%, #15719e 45%, #4da3c9 100%)', color: '#fff', position: 'relative', overflow: 'hidden' }}>

      {/* Ambient waves bg */}
      <svg viewBox="0 0 400 700" preserveAspectRatio="none"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.4 }}>
        <path d="M0 420 C 80 400, 160 460, 240 430 S 400 410, 400 430 L400 700 L0 700 Z" fill="#f4e5b9"/>
        <path d="M0 400 C 80 380, 160 440, 240 410 S 400 390, 400 410" stroke="#ffffff" strokeWidth="1" opacity="0.5" fill="none"/>
        <path d="M0 360 C 80 350, 160 380, 240 360 S 400 350, 400 360" stroke="#ffffff" strokeWidth="1" opacity="0.3" fill="none"/>
        <circle cx="320" cy="120" r="50" fill="#ffd97a" opacity="0.85"/>
      </svg>

      <div style={{ position: 'relative', padding: '12px 22px 0', zIndex: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 24 }}>
          <div style={{ width: 34, height: 34, borderRadius: 10, background: 'rgba(255,255,255,0.22)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(8px)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M2 14c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 18c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" stroke="#fff" strokeWidth="2" strokeLinecap="round"/></svg>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Surf Health</span>
        </div>

        <h1 style={{ fontSize: 38, fontWeight: 700, lineHeight: 1.02, marginTop: 38, maxWidth: 320 }}>
          Find out if the water's clean<span style={{ opacity: 0.7 }}>—before you paddle out.</span>
        </h1>
        <p style={{ fontSize: 15, opacity: 0.82, marginTop: 16, lineHeight: 1.5, maxWidth: 320 }}>
          Daily bacteria + surf forecast for 480+ California beaches.
        </p>
      </div>

      {/* Lower sheet */}
      <div style={{ marginTop: 'auto', background: '#fff', color: '#0f172a',
        borderRadius: '28px 28px 0 0', padding: '22px 20px 28px', zIndex: 3, boxShadow: '0 -20px 60px rgba(0,0,0,0.2)' }}>

        <button onClick={() => onPick && onPick(beaches.find(b => b.id === 'manhattan-beach-pier'))}
          style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12,
            padding: '14px 16px', borderRadius: 14, border: 'none',
            background: 'linear-gradient(180deg, #0b4266, #083854)', color: '#fff',
            fontSize: 15, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer', marginBottom: 12 }}>
          <Icon.locate /> Use current location
          <span style={{ marginLeft: 'auto', fontSize: 12, opacity: 0.7, fontWeight: 500 }}>Manhattan Beach</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#f1f5f9',
          borderRadius: 14, padding: '12px 14px', border: `1px solid ${focused ? '#0b4266' : 'transparent'}`, transition: 'border-color 150ms' }}>
          <Icon.search style={{ color: '#64748b' }} />
          <input value={q} onChange={e => setQ(e.target.value)}
            onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
            placeholder="Search beaches, cities, counties"
            style={{ border: 'none', background: 'transparent', outline: 'none',
              flex: 1, fontFamily: 'inherit', fontSize: 15, color: '#0f172a' }}/>
        </div>

        {q ? (
          <div style={{ marginTop: 14, maxHeight: 210, overflowY: 'auto' }}>
            {results.map(b => (
              <button key={b.id} onClick={() => onPick && onPick(b)}
                className={riskClass(b.risk)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 4px', border: 'none', background: 'none', cursor: 'pointer',
                  borderBottom: '1px solid #f1f5f9', fontFamily: 'inherit', textAlign: 'left' }}>
                <span className="sh-dot"/>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{b.county} County · {b.region}</div>
                </div>
                <Icon.chevron style={{ color: '#cbd5e1' }}/>
              </button>
            ))}
            {!results.length && <div style={{ fontSize: 13, color: '#64748b', padding: '12px 4px' }}>No matches — try another search.</div>}
          </div>
        ) : (
          <>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 18, marginBottom: 8 }}>Recent</div>
            {recent.map(b => (
              <button key={b.id} onClick={() => onPick && onPick(b)}
                className={riskClass(b.risk)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 4px', border: 'none', background: 'none', cursor: 'pointer',
                  fontFamily: 'inherit', textAlign: 'left' }}>
                <span className="sh-dot"/>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{b.county} · {b.waveFt}ft · {b.temp}°F</div>
                </div>
                <Icon.chevron style={{ color: '#cbd5e1' }}/>
              </button>
            ))}
            <button onClick={() => onPick && onPick({ region: 'browse' })}
              style={{ width: '100%', marginTop: 14, padding: '12px', border: '1px solid #e2e8f0',
                borderRadius: 12, background: '#fff', color: '#0b4266', fontWeight: 600,
                fontFamily: 'inherit', fontSize: 14, cursor: 'pointer' }}>
              Browse map →
            </button>
          </>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { LocationSelectScreen });
