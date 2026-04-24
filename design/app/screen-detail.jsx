// Beach detail — forecast, drivers, environmental, weekly outlook

function DetailScreen({ beach, onBack }) {
  const meta = window.RISK_META[beach.risk];
  const [fav, setFav] = React.useState(false);

  const week = [
    { d: 'Mon', risk: beach.risk, waveFt: beach.waveFt },
    { d: 'Tue', risk: beach.risk === 'Low' ? 'Low' : 'Moderate', waveFt: beach.waveFt + 0.3 },
    { d: 'Wed', risk: 'Low', waveFt: beach.waveFt + 0.5 },
    { d: 'Thu', risk: 'Low', waveFt: beach.waveFt + 0.8 },
    { d: 'Fri', risk: 'Moderate', waveFt: beach.waveFt - 0.2 },
    { d: 'Sat', risk: 'High', waveFt: beach.waveFt - 0.4 },
    { d: 'Sun', risk: 'Moderate', waveFt: beach.waveFt - 0.1 },
  ];

  const drivers = beach.risk === 'Low' ? [
    { t: 'No recent rainfall', d: 'Last significant rain 11 days ago — runoff has cleared.', good: true },
    { t: 'Steady salinity', d: 'Within seasonal norms, no freshwater plume detected.', good: true },
    { t: 'Clean 3-sample trend', d: 'Enterococcus below 35 CFU/100mL for 21 days.', good: true },
  ] : beach.risk === 'Moderate' ? [
    { t: 'Borderline persistence', d: 'Recent samples near the STV threshold.', good: false },
    { t: 'Light onshore wind', d: '5–8mph onshore may concentrate bacteria nearshore.', good: false },
    { t: 'Normal salinity', d: 'No active runoff signal.', good: true },
  ] : [
    { t: 'Recent rainfall', d: '0.4" fell 36 hours ago — runoff still elevated.', good: false },
    { t: 'Strong onshore wind', d: '8+mph onshore flow concentrating bacteria.', good: false },
    { t: 'Active advisory', d: 'County public-health posting in effect since Sat.', good: false },
  ];

  return (
    <div className={`sh-app ${riskClass(beach.risk)}`}
      style={{ '--sh-bg': '#f2f4f7', '--sh-text': '#0f172a', '--sh-muted': '#64748b',
        '--sh-surface': '#fff', '--sh-border': '#e5e7eb', '--sh-accent': '#0b4266',
        height: '100%', overflowY: 'auto', paddingBottom: 30 }}>

      {/* Hero photo */}
      <div style={{ position: 'relative', height: 260 }}>
        <BeachArt band={beach.risk} seed={beach.lat} style={{ position: 'absolute', inset: 0, height: '100%' }}/>
        <div style={{ position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, rgba(0,0,0,0.35) 0%, transparent 40%, rgba(0,0,0,0.55) 100%)' }}/>
        {/* top bar */}
        <div style={{ position: 'absolute', top: 12, left: 16, right: 16, display: 'flex', gap: 10 }}>
          <button onClick={onBack} style={{ width: 38, height: 38, borderRadius: 12,
            background: 'rgba(255,255,255,0.25)', backdropFilter: 'blur(12px)', border: 'none', color: '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}><Icon.back/></button>
          <div style={{ flex: 1 }}/>
          <button onClick={() => setFav(!fav)} style={{ width: 38, height: 38, borderRadius: 12,
            background: 'rgba(255,255,255,0.25)', backdropFilter: 'blur(12px)', border: 'none',
            color: fav ? '#fbbf24' : '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
            {fav ? <Icon.starFilled/> : <Icon.star/>}
          </button>
        </div>
        {/* bottom label */}
        <div style={{ position: 'absolute', left: 20, right: 20, bottom: 18, color: '#fff' }}>
          <div style={{ fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase', opacity: 0.85, fontWeight: 600 }}>
            {beach.county} County · {beach.region}
          </div>
          <h1 style={{ fontSize: 30, fontWeight: 700, marginTop: 4 }}>{beach.name}</h1>
        </div>
      </div>

      {/* Risk banner */}
      <div style={{ padding: '18px 20px 0' }}>
        <div style={{ background: 'var(--risk-bg)', color: 'var(--risk-deep)',
          borderRadius: 18, padding: 16, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ width: 44, height: 44, borderRadius: 14, background: 'var(--risk)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', flexShrink: 0 }}>
            <Icon.drop style={{ width: 22, height: 22 }}/>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              Water quality · today
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 3 }}>{meta.label}</div>
            <div style={{ fontSize: 13, marginTop: 4, opacity: 0.9, lineHeight: 1.4 }}>{meta.advice}</div>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>{Math.round(beach.p*100)}<span style={{ fontSize: 14 }}>%</span></div>
            <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.75 }}>exceed chance</div>
          </div>
        </div>
      </div>

      {/* Conditions grid */}
      <div style={{ padding: '24px 20px 0' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
          letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Conditions</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <GridStat icon={<Icon.waves/>} label="Surf" big={`${beach.waveFt}ft`} sub={`${beach.period}s period`}/>
          <GridStat icon={<Icon.thermo/>} label="Water" big={`${beach.temp}°F`} sub="+0.3 vs yday"/>
          <GridStat icon={<Icon.wind/>} label="Wind" big={`${beach.wind}mph`} sub="Onshore W"/>
          <GridStat icon={<Icon.sun/>} label="UV" big={beach.uv} sub={beach.uv >= 7 ? 'Very high' : 'Moderate'}/>
          <GridStat icon={<Icon.tide/>} label="Tide" big={beach.tide} sub="Next high 2:14p"/>
          <GridStat icon={<Icon.people/>} label="Crowd" big={beach.crowd} sub="typical for 10a"/>
        </div>
      </div>

      {/* Drivers */}
      <div style={{ padding: '24px 20px 0' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
          letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>What's driving the forecast</div>
        <div style={{ background: '#fff', borderRadius: 18, border: '1px solid #e5e7eb', overflow: 'hidden' }}>
          {drivers.map((d, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: 14,
              borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
              <div style={{ width: 26, height: 26, borderRadius: 8, flexShrink: 0,
                background: d.good ? '#dcfce7' : '#fee2e2', color: d.good ? '#15803d' : '#b91c1c',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700 }}>
                {d.good ? '✓' : '!'}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{d.t}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2, lineHeight: 1.4 }}>{d.d}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Weekly */}
      <div style={{ padding: '24px 20px 0' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
          letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>7-day outlook</div>
        <div style={{ background: '#fff', borderRadius: 18, border: '1px solid #e5e7eb', padding: 14 }}>
          {week.map((w, i) => (
            <div key={i} className={riskClass(w.risk)}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0',
                borderTop: i ? '1px solid #f8fafc' : 'none' }}>
              <div style={{ width: 36, fontSize: 13, fontWeight: 600, color: i === 0 ? '#0b4266' : '#0f172a' }}>
                {i === 0 ? 'Today' : w.d}
              </div>
              <div style={{ flex: 1, height: 6, background: '#f1f5f9', borderRadius: 3, position: 'relative' }}>
                <div style={{ position: 'absolute', inset: 0, width: `${(w.waveFt/6)*100}%`,
                  background: 'linear-gradient(90deg, #0ea5e9, #0b4266)', borderRadius: 3 }}/>
              </div>
              <div style={{ fontSize: 12, width: 42, textAlign: 'right', color: '#64748b', fontWeight: 600 }}>
                {w.waveFt.toFixed(1)}ft
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '3px 8px', borderRadius: 999, background: 'var(--risk-bg)',
                color: 'var(--risk-deep)', fontSize: 10, fontWeight: 700, width: 70, justifyContent: 'center' }}>
                <span className="sh-dot" style={{ width: 6, height: 6 }}/>{w.risk}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Sample card */}
      <div style={{ padding: '24px 20px 0' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
          letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Last official sample</div>
        <div style={{ background: '#fff', borderRadius: 18, border: '1px solid #e5e7eb', padding: 16,
          display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: '#f1f5f9',
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#0b4266' }}>
            <Icon.flask/>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>5 days ago · Apr 18</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>81 CFU/100mL enterococcus</div>
          </div>
          <div style={{ fontSize: 11, color: '#15803d', fontWeight: 700 }}>Under STV</div>
        </div>
      </div>
    </div>
  );
}

function GridStat({ icon, label, big, sub }) {
  return (
    <div style={{ padding: 14, background: '#fff', borderRadius: 16, border: '1px solid #e5e7eb' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: '#64748b' }}>
        {icon}<span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{big}</div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{sub}</div>
    </div>
  );
}

Object.assign(window, { DetailScreen });
