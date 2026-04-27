// Home page — travel poster aesthetic
// Header · hero (poster map + answer block) · cross-section panel · grid · spotlight · footer

function SiteHeader({ active = 'Forecast' }) {
  return (
    <header style={{
      position: 'relative', zIndex: 5,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '24px 64px', borderBottom: '1px solid var(--sl-line)',
      background: 'var(--sl-ecru)',
    }}>
      <LockupHorizontal size={28} subtitle="California Water Quality"/>
      <nav style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
        {['Forecast', 'Beaches', 'Research', 'Methodology'].map(item => (
          <a key={item} href="#" style={{
            fontFamily: 'var(--sl-mono)', fontSize: 11, letterSpacing: '0.16em',
            textTransform: 'uppercase', textDecoration: 'none',
            color: active === item ? 'var(--sl-navy)' : 'var(--sl-muted)',
            fontWeight: active === item ? 600 : 500,
            paddingBottom: 4,
            borderBottom: active === item ? '1.5px solid var(--sl-navy)' : '1.5px solid transparent',
          }}>{item}</a>
        ))}
        <a href="#" style={{
          fontFamily: 'var(--sl-mono)', fontSize: 11, letterSpacing: '0.16em',
          textTransform: 'uppercase', textDecoration: 'none',
          padding: '8px 16px', borderRadius: 999,
          background: 'var(--sl-navy)', color: 'var(--sl-bone)',
        }}>Get the App ↗</a>
      </nav>
    </header>
  );
}

function HomePage({ heroBand = 'Low' }) {
  const [activeBeach, setActiveBeach] = React.useState(
    () => window.BEACHES.find(b => b.id === 'malibu') || window.BEACHES[0]
  );
  const copy = RISK_COPY[heroBand];
  const tok = RISK_TOKEN[heroBand];

  // Featured beaches for spotlight
  const featured = React.useMemo(() => {
    const picks = ['malibu', 'rincon', 'venice', 'huntington', 'ocean-beach-sf', 'imperial-beach',
      'steamer-lane', 'la-jolla-shores', 'monterey'];
    return picks.map(id => window.BEACHES.find(b => b.id === id)).filter(Boolean);
  }, []);

  return (
    <div style={{ position: 'relative', zIndex: 1 }}>
      <SiteHeader active="Forecast"/>

      {/* HERO */}
      <section style={{ padding: '48px 64px 32px', display: 'grid',
        gridTemplateColumns: '1fr 580px', gap: 48, alignItems: 'start' }}>
        <div>
          <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>
            ◐ Live forecast · Apr 27, 2026 · 5:02a PT
          </div>
          <h1 className="sl-display" style={{
            fontSize: 92, marginTop: 18, marginBottom: 0,
            color: 'var(--sl-navy-ink)', maxWidth: 720,
          }}>
            Know before you<br/>paddle out.
          </h1>
          <p style={{ fontSize: 18, color: 'var(--sl-ink)', lineHeight: 1.55,
            maxWidth: 540, marginTop: 24 }}>
            Shorelife turns sparse official bacteria samples plus ocean and weather context into a
            daily health-risk forecast for <span style={{ color: 'var(--sl-navy)', fontWeight: 600 }}>
            {window.BEACHES.length}+ California marine beaches</span>.
          </p>

          {/* Live answer card — changes with risk band tweak */}
          <div style={{ marginTop: 36, display: 'inline-flex', alignItems: 'stretch',
            background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
            borderRadius: 14, overflow: 'hidden',
            boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 8px 24px rgba(11,66,102,0.06)',
          }}>
            <div style={{ background: tok.bg, padding: '20px 24px',
              display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
              minWidth: 200, borderRight: `1px solid var(--sl-line)` }}>
              <div className="sl-label" style={{ color: tok.ink }}>{heroBand.toUpperCase()}</div>
              <div className="sl-display" style={{
                fontSize: 56, color: tok.ink, lineHeight: 0.9, marginTop: 18,
              }}>{copy.head}</div>
              <DropRow band={heroBand} size={14}/>
            </div>
            <div style={{ padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 280 }}>
              <div>
                <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Today at Malibu Surfrider</div>
                <div style={{ fontSize: 14, color: 'var(--sl-ink)', marginTop: 6, lineHeight: 1.5, maxWidth: 280 }}>
                  {copy.sub}
                </div>
              </div>
              <SeverityBar band={heroBand} width="100%"/>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                fontFamily: 'var(--sl-mono)', fontSize: 11, color: 'var(--sl-muted)',
                paddingTop: 10, borderTop: '1px dashed var(--sl-line)' }}>
                <span>ENT · {copy.cfu}</span>
                <span>SAMPLED · 2d ago</span>
              </div>
            </div>
          </div>

          {/* Quick stats below */}
          <div style={{ display: 'flex', gap: 48, marginTop: 36 }}>
            {[
              { k: window.BEACHES.length, l: 'monitored stations' },
              { k: '5:00a PT', l: 'daily publish' },
              { k: '4', l: 'risk bands' },
            ].map(s => (
              <div key={s.l}>
                <div className="sl-display" style={{ fontSize: 36, color: 'var(--sl-navy)' }}>{s.k}</div>
                <div className="sl-label" style={{ color: 'var(--sl-muted)', marginTop: 4 }}>{s.l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Coast map */}
        <div>
          <CaliforniaPosterMap
            band={heroBand}
            beaches={window.BEACHES}
            activeBeach={activeBeach}
            onSelect={setActiveBeach}
            height={680}/>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12,
            fontFamily: 'var(--sl-mono)', fontSize: 10, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
            <span>Fig. 01 · Statewide nearshore health board</span>
            <span>Hover stations →</span>
          </div>
        </div>
      </section>

      {/* CROSS-SECTION INTERLUDE */}
      <section style={{ padding: '32px 64px 0' }}>
        <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>02 · How we read the shoreline</div>
        <h2 className="sl-display" style={{ fontSize: 48, marginTop: 12, marginBottom: 24,
          color: 'var(--sl-navy-ink)', maxWidth: 720 }}>
          A model of the surf zone, not just a number.
        </h2>
        <div style={{ borderRadius: 14, overflow: 'hidden', border: '1px solid var(--sl-line)',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset' }}>
          <ShorelineCrossSection band={heroBand} height={340}/>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 18, marginTop: 22 }}>
          {[
            { k: 'A · Offshore',   v: 'NDBC buoy swell height, period, direction' },
            { k: 'B · Mid-shelf',  v: 'CDIP nearshore wave model + SST' },
            { k: 'C · Surf zone',  v: 'culture sample history + exceedance prior' },
            { k: 'D · Swash',      v: 'tide stage, runoff index, last advisory' },
          ].map(c => (
            <div key={c.k} style={{ paddingTop: 12, borderTop: '1px solid var(--sl-line)' }}>
              <div className="sl-label" style={{ color: 'var(--sl-navy)' }}>{c.k}</div>
              <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 6, lineHeight: 1.5 }}>{c.v}</div>
            </div>
          ))}
        </div>
      </section>

      {/* WHY THIS MATTERS — three audience cards */}
      <section style={{ padding: '64px 64px 0' }}>
        <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>03 · Who it's for</div>
        <h2 className="sl-display" style={{ fontSize: 48, marginTop: 12, marginBottom: 36,
          color: 'var(--sl-navy-ink)' }}>
          Health risk is the missing beach signal.
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
          {[
            { who: 'For surfers', body: 'Check a beach card that combines surf context and water-health risk before you paddle out with a cut, a weak immune system, or after rain.', icon: '◐' },
            { who: 'For agencies', body: 'Use same-day probability estimates to prioritize field visits, spot persistent hot spots, and communicate uncertainty instead of waiting on the next lab run.', icon: '◑' },
            { who: 'For researchers', body: 'Compare official enterococcus labels against nearshore covariates, blocked backtests, and calibrated exceedance forecasts from strong baselines.', icon: '◒' },
          ].map(c => (
            <article key={c.who} style={{
              background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 14, padding: 28,
            }}>
              <div style={{ fontSize: 28, color: 'var(--sl-sun-deep)', lineHeight: 1 }}>{c.icon}</div>
              <h3 className="sl-display" style={{ fontSize: 24, marginTop: 18, marginBottom: 10,
                color: 'var(--sl-navy)' }}>{c.who}</h3>
              <p style={{ fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.6, margin: 0 }}>{c.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* TODAY'S FORECAST — spotlight grid */}
      <section style={{ padding: '64px 64px 0' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 28 }}>
          <div>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>04 · Today's forecast</div>
            <h2 className="sl-display" style={{ fontSize: 48, marginTop: 12,
              color: 'var(--sl-navy-ink)' }}>
              What's in the water right now.
            </h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <select style={{
              fontFamily: 'var(--sl-mono)', fontSize: 11, letterSpacing: '0.10em',
              padding: '8px 14px', borderRadius: 999, border: '1px solid var(--sl-line)',
              background: 'var(--sl-bone)', color: 'var(--sl-ink)', textTransform: 'uppercase',
            }}>
              <option>All counties</option><option>Los Angeles</option><option>Orange</option>
            </select>
            <button style={{
              fontFamily: 'var(--sl-mono)', fontSize: 11, letterSpacing: '0.10em',
              padding: '8px 14px', borderRadius: 999, border: '1px solid var(--sl-line)',
              background: 'transparent', color: 'var(--sl-muted)', textTransform: 'uppercase', cursor: 'pointer',
            }}>★ Favorites</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
          {featured.map(b => {
            const tok2 = RISK_TOKEN[b.risk];
            return (
              <article key={b.id} style={{
                background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
                borderRadius: 14, padding: 22, display: 'flex', flexDirection: 'column', gap: 12,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>{b.county}</div>
                    <h3 className="sl-display" style={{ fontSize: 22, margin: '6px 0 0', color: 'var(--sl-navy)' }}>{b.name}</h3>
                  </div>
                  <RiskChip band={b.risk}/>
                </div>
                <div style={{ paddingTop: 10, borderTop: '1px dashed var(--sl-line)',
                  display: 'flex', justifyContent: 'space-between',
                  fontFamily: 'var(--sl-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>
                  <span>{b.waveFt}ft @ {b.period}s</span>
                  <span>{b.temp}°F</span>
                  <span style={{ color: tok2.ink }}>{Math.round(b.p * 100)}% exceed</span>
                </div>
                <SeverityBar band={b.risk} width="100%" height={4}/>
              </article>
            );
          })}
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{ padding: '80px 64px 48px', marginTop: 64,
        borderTop: '1px solid var(--sl-line)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 48 }}>
          <div>
            <LockupHorizontal size={24} subtitle="California Water Quality"/>
            <p style={{ fontSize: 13, color: 'var(--sl-muted)', lineHeight: 1.6, marginTop: 18, maxWidth: 380 }}>
              Daily marine-water health forecasts for California beaches. A model forecast — not an official lab result.
              Treat advisories as advisory.
            </p>
          </div>
          {[
            { t: 'Product', l: ['Forecast', 'Beach explorer', 'iOS app', 'Share links'] },
            { t: 'Science', l: ['Methodology', 'Research', 'Sources', 'Caveats'] },
            { t: 'About', l: ['Mission', 'Team', 'Contact', 'Press kit'] },
          ].map(c => (
            <div key={c.t}>
              <div className="sl-label" style={{ color: 'var(--sl-navy)' }}>{c.t}</div>
              <ul style={{ listStyle: 'none', padding: 0, margin: '14px 0 0',
                display: 'flex', flexDirection: 'column', gap: 8 }}>
                {c.l.map(li => <li key={li} style={{ fontSize: 13, color: 'var(--sl-muted)' }}>{li}</li>)}
              </ul>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 48, paddingTop: 24, borderTop: '1px solid var(--sl-line)',
          display: 'flex', justifyContent: 'space-between',
          fontFamily: 'var(--sl-mono)', fontSize: 10, letterSpacing: '0.16em',
          textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
          <span>© 2026 Shorelife · v1.0</span>
          <span>Made on the Pacific coast</span>
        </div>
      </footer>
    </div>
  );
}

Object.assign(window, { HomePage, SiteHeader });
