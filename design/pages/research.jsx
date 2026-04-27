// Research / ops page — denser, mono-numeric, model registry

function ResearchPage() {
  const stations = window.BEACHES.slice(0, 12);

  return (
    <div>
      <SiteHeader active="Research"/>

      <div style={{ padding: '48px 64px 64px' }}>
        <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Research · operator view · build 2026.04.27</div>
        <h1 className="sl-display" style={{ fontSize: 80, marginTop: 14, marginBottom: 16,
          color: 'var(--sl-navy-ink)' }}>
          Model health &<br/>deployment traceability.
        </h1>
        <p style={{ fontSize: 17, color: 'var(--sl-ink)', lineHeight: 1.55,
          maxWidth: 720, margin: 0 }}>
          The operator view tracks model registry status, source freshness, and which stations are
          ready for production versus beta fallback.
        </p>

        {/* Registry stats — large mono-numeric strip */}
        <div style={{ marginTop: 56, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 0,
          background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14,
          overflow: 'hidden' }}>
          {[
            ['Production model', 'gbdt-marine-v1.4', 'sl-display', 22],
            ['Test AUCPR', '0.7421', 'sl-mono', 28],
            ['Test Brier', '0.0986', 'sl-mono', 28],
            ['Coverage', '38 / 12', 'sl-mono', 28, 'production / beta'],
            ['Public release', 'Eligible', 'sl-display', 22],
          ].map((r, i) => (
            <div key={i} style={{ padding: '24px 24px',
              borderRight: i < 4 ? '1px solid var(--sl-line-soft)' : 'none' }}>
              <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>{r[0]}</div>
              <div className={r[2]} style={{ fontSize: r[3], color: 'var(--sl-navy-ink)', marginTop: 12 }}>{r[1]}</div>
              {r[4] && <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)', marginTop: 4 }}>{r[4]}</div>}
            </div>
          ))}
        </div>

        {/* Two-column: source freshness + station coverage */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 32, marginTop: 32 }}>
          {/* Source freshness */}
          <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
            borderRadius: 14, padding: 28 }}>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Source freshness</div>
            <h2 className="sl-display" style={{ fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)' }}>
              Pipeline heartbeat
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {[
                ['CA Beach Watch (CDPH)', '2h ago', 'fresh'],
                ['NDBC buoy network', '38m ago', 'fresh'],
                ['CDIP nearshore', '52m ago', 'fresh'],
                ['NOAA water temp (SST)', '6h ago', 'fresh'],
                ['NWS forecast grids', '11m ago', 'fresh'],
                ['Open-Meteo UV', '14m ago', 'fresh'],
                ['Storm Drains GIS', '2d ago', 'stale'],
              ].map(([src, age, state], i) => (
                <div key={src} style={{ display: 'flex', justifyContent: 'space-between',
                  padding: '14px 0', borderTop: i ? '1px solid var(--sl-line-soft)' : 'none' }}>
                  <span style={{ fontSize: 13, color: 'var(--sl-ink)' }}>{src}</span>
                  <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <span className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)' }}>{age}</span>
                    <span className="sl-mono" style={{ fontSize: 9, fontWeight: 600,
                      letterSpacing: '0.14em', textTransform: 'uppercase',
                      padding: '3px 8px', borderRadius: 999,
                      background: state === 'fresh' ? 'var(--sl-risk-low-bg)' : 'var(--sl-risk-mod-bg)',
                      color: state === 'fresh' ? 'var(--sl-risk-low-ink)' : 'var(--sl-risk-mod-ink)' }}>
                      {state}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Station coverage */}
          <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
            borderRadius: 14, padding: 28 }}>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Station state</div>
            <h2 className="sl-display" style={{ fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)' }}>
              Current forecast coverage
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {stations.map(s => (
                <div key={s.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '11px 14px', borderRadius: 10,
                  background: 'var(--sl-ecru)', border: '1px solid var(--sl-line-soft)' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--sl-ink)',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {s.name}
                    </div>
                    <div className="sl-mono" style={{ fontSize: 9.5, color: 'var(--sl-muted)',
                      letterSpacing: '0.06em', marginTop: 2 }}>
                      gbdt-v1.4 · production
                    </div>
                  </div>
                  <RiskChip band={s.risk}/>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Spatial holdout table */}
        <div style={{ marginTop: 32, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
          borderRadius: 14, padding: 28 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 24 }}>
            <div>
              <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Validation</div>
              <h2 className="sl-display" style={{ fontSize: 28, margin: '8px 0 0', color: 'var(--sl-navy-ink)' }}>
                Spatial holdouts
              </h2>
            </div>
            <span className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)' }}>
              blocked time-series + held-out region
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1,
            background: 'var(--sl-line-soft)', borderRadius: 10, overflow: 'hidden' }}>
            {[['HOLDOUT', 'AUCPR', 'BRIER', 'N SAMPLES'],
              ['SoCal',  '0.7612', '0.0921', '4,182'],
              ['Central','0.7204', '0.1042', '2,667'],
              ['NorCal', '0.6918', '0.1184', '1,503'],
              ['All',    '0.7421', '0.0986', '8,352']].map((row, i) => (
              <React.Fragment key={i}>
                {row.map((cell, j) => (
                  <div key={j} style={{ background: 'var(--sl-ecru)', padding: '14px 18px',
                    fontFamily: i === 0 ? 'var(--sl-mono)' : (j === 0 ? 'var(--sl-display)' : 'var(--sl-mono)'),
                    fontSize: i === 0 ? 10 : (j === 0 ? 17 : 14),
                    fontWeight: i === 0 ? 500 : (j === 0 ? 500 : 400),
                    letterSpacing: i === 0 ? '0.14em' : '0',
                    textTransform: i === 0 ? 'uppercase' : 'none',
                    color: i === 0 ? 'var(--sl-muted)' : (j === 0 ? 'var(--sl-navy)' : 'var(--sl-ink)'),
                  }}>{cell}</div>
                ))}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ResearchPage });
