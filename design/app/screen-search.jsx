// Search / browse screen — filter by region, county, risk, surf

function SearchScreen({ beaches, onPick, onBack }) {
  const [q, setQ] = React.useState('');
  const [region, setRegion] = React.useState('All');
  const [sort, setSort] = React.useState('name');

  const regions = ['All', 'SoCal', 'Central', 'NorCal'];
  const filtered = beaches
    .filter(b => region === 'All' || b.region === region)
    .filter(b => !q || b.name.toLowerCase().includes(q.toLowerCase()) || b.county.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'safest') return a.p - b.p;
      if (sort === 'wave') return b.waveFt - a.waveFt;
      return 0;
    });

  // group by region
  const grouped = {};
  filtered.forEach(b => { (grouped[b.region] = grouped[b.region] || []).push(b); });
  const regionOrder = ['SoCal', 'Central', 'NorCal'];

  return (
    <div className="sh-app" style={{ '--sh-bg': '#f2f4f7', '--sh-text': '#0f172a', '--sh-muted': '#64748b',
      '--sh-surface': '#fff', '--sh-border': '#e5e7eb', '--sh-accent': '#0b4266',
      '--sh-tab-bg': 'rgba(255,255,255,0.92)',
      height: '100%', overflowY: 'auto', paddingBottom: 90, background: '#f2f4f7' }}>

      <div style={{ padding: '16px 20px 0', background: '#fff', borderBottom: '1px solid #e5e7eb', position: 'sticky', top: 0, zIndex: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
          <button onClick={onBack} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>
            <Icon.back/>
          </button>
          <h1 style={{ fontSize: 22, fontWeight: 700, flex: 1 }}>Browse beaches</h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#f1f5f9',
          borderRadius: 12, padding: '10px 12px', marginTop: 12 }}>
          <Icon.search style={{ color: '#64748b' }}/>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search 480+ beaches"
            style={{ flex: 1, border: 'none', background: 'transparent', outline: 'none',
              fontFamily: 'inherit', fontSize: 14 }}/>
          {q && <button onClick={() => setQ('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8' }}><Icon.close/></button>}
        </div>
        <div style={{ display: 'flex', gap: 6, margin: '12px 0', overflowX: 'auto' }}>
          {regions.map(r => (
            <button key={r} onClick={() => setRegion(r)}
              style={{ padding: '6px 12px', borderRadius: 999,
                border: '1px solid ' + (region === r ? '#0b4266' : '#e5e7eb'),
                background: region === r ? '#0b4266' : '#fff',
                color: region === r ? '#fff' : '#0f172a',
                fontSize: 12, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap' }}>
              {r}
            </button>
          ))}
          <div style={{ marginLeft: 'auto' }}>
            <select value={sort} onChange={e => setSort(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 999, border: '1px solid #e5e7eb',
                background: '#fff', fontFamily: 'inherit', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              <option value="name">A–Z</option>
              <option value="safest">Safest first</option>
              <option value="wave">Biggest surf</option>
            </select>
          </div>
        </div>
      </div>

      {regionOrder.filter(r => grouped[r]).map(r => (
        <div key={r} style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: '0.08em',
            textTransform: 'uppercase', padding: '0 20px', marginBottom: 8,
            display: 'flex', justifyContent: 'space-between' }}>
            <span>{r === 'SoCal' ? 'Southern California' : r === 'Central' ? 'Central California' : 'Northern California'}</span>
            <span style={{ opacity: 0.6 }}>{grouped[r].length}</span>
          </div>
          <div style={{ padding: '0 20px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {grouped[r].map((b, i) => (
              <button key={b.id} onClick={() => onPick && onPick(b)}
                className={riskClass(b.risk)}
                style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12,
                  background: '#fff', border: '1px solid #e5e7eb', borderRadius: 14, cursor: 'pointer',
                  fontFamily: 'inherit', textAlign: 'left', width: '100%' }}>
                <span className="sh-dot" style={{ width: 10, height: 10 }}/>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {b.county} · {b.waveFt}ft · {b.temp}°
                  </div>
                </div>
                <Icon.chevron style={{ color: '#cbd5e1' }}/>
              </button>
            ))}
          </div>
        </div>
      ))}

      {!filtered.length && (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: '#64748b' }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>No beaches match</div>
          <div style={{ fontSize: 13, marginTop: 4 }}>Try a different search or region.</div>
        </div>
      )}

      <TabBar current="search" onOpenHome={onBack}/>
    </div>
  );
}

Object.assign(window, { SearchScreen });
