// Methodology page — editorial long-read, hairlines, sidenotes

function MethodologyPage() {
  return (
    <div>
      <SiteHeader active="Methodology"/>

      <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>
        <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Methodology · v1.0 · Apr 2026</div>
        <h1 className="sl-display" style={{ fontSize: 96, marginTop: 18, marginBottom: 32,
          color: 'var(--sl-navy-ink)', maxWidth: 980 }}>
          How the forecast<br/>is built.
        </h1>
        <p style={{ fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 720, margin: 0 }}>
          Shorelife models marine enterococcus risk using official California sample history and daily
          environmental context from nearshore ocean and weather sources. We publish a calibrated
          exceedance probability, banded into four public-facing risk levels.
        </p>

        {/* Two-column editorial */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div className="sl-label" style={{ color: 'var(--sl-navy)' }}>§ 01</div>
            <div className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)',
              marginTop: 8, lineHeight: 1.6 }}>
              MODEL DESIGN
            </div>
          </aside>
          <div>
            <h2 className="sl-display" style={{ fontSize: 40, margin: '0 0 24px',
              color: 'var(--sl-navy-ink)' }}>
              Numerically grounded by default.
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
              {[
                ['Label policy', 'V1 uses culture-based marine enterococcus only. Freshwater E. coli, total coliform, fecal coliform, and ddPCR stay in the warehouse but outside the pooled forecast label.'],
                ['Daily forecast', 'We train only on observed sample days, then infer unsampled days from sliding-window history instead of pseudo-labeling the gaps.'],
                ['Baselines first', 'Persistence, logistic/linear, and gradient-boosted tree baselines are mandatory. The neural model stays research-only until it clears blocked-time and explicit spatial holdout gates.'],
                ['Calibration', 'Public-facing bands come from calibrated exceedance probabilities with a stronger penalty on false negatives than false positives.'],
              ].map(([h, b]) => (
                <div key={h} style={{ paddingTop: 20, borderTop: '1px solid var(--sl-line-soft)' }}>
                  <h3 className="sl-display" style={{ fontSize: 22, margin: '0 0 10px', color: 'var(--sl-navy)' }}>{h}</h3>
                  <p style={{ fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.65, margin: 0 }}>{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Risk band table */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div className="sl-label" style={{ color: 'var(--sl-navy)' }}>§ 02</div>
            <div className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)',
              marginTop: 8, lineHeight: 1.6 }}>
              RISK BANDS
            </div>
          </aside>
          <div>
            <h2 className="sl-display" style={{ fontSize: 40, margin: '0 0 28px',
              color: 'var(--sl-navy-ink)' }}>
              Four bands, calibrated for public alerts.
            </h2>
            <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 14, overflow: 'hidden' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr 80px',
                padding: '14px 22px', borderBottom: '1px solid var(--sl-line)',
                fontFamily: 'var(--sl-mono)', fontSize: 10, letterSpacing: '0.14em',
                textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
                <span>Band</span><span>Headline</span><span>Guidance</span><span>Enterococcus</span><span>Drops</span>
              </div>
              {RISK_ORDER.map(band => {
                const c = RISK_COPY[band];
                return (
                  <div key={band} style={{
                    display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr 80px',
                    padding: '20px 22px', alignItems: 'center',
                    borderBottom: band === 'Very High' ? 'none' : '1px solid var(--sl-line-soft)',
                  }}>
                    <span><RiskChip band={band}/></span>
                    <span className="sl-display" style={{ fontSize: 22, color: 'var(--sl-navy)' }}>{c.head}</span>
                    <span style={{ fontSize: 13, color: 'var(--sl-ink)', lineHeight: 1.5 }}>{c.sub}</span>
                    <span className="sl-mono" style={{ fontSize: 12, color: 'var(--sl-ink)' }}>{c.cfu}</span>
                    <span><DropRow band={band} size={12}/></span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Caveats */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div className="sl-label" style={{ color: 'var(--sl-risk-vh)' }}>§ 03</div>
            <div className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)',
              marginTop: 8, lineHeight: 1.6 }}>
              LIMITS
            </div>
          </aside>
          <div>
            <h2 className="sl-display" style={{ fontSize: 40, margin: '0 0 24px',
              color: 'var(--sl-navy-ink)' }}>
              What this model can't do.
            </h2>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0,
              display: 'flex', flexDirection: 'column', gap: 16 }}>
              {[
                'Forecasts complement official monitoring; they do not replace county advisories.',
                'Sparse sites may remain in beta mode with wider prediction intervals.',
                'Heavy storm, sewage, or spill events can outrun any historical statistical model.',
                'LLM explanations summarize the forecast; the numeric risk comes from the ML model.',
              ].map((li, i) => (
                <li key={i} style={{ display: 'flex', gap: 16, paddingTop: 16,
                  borderTop: '1px dashed var(--sl-line)', fontSize: 16,
                  color: 'var(--sl-ink)', lineHeight: 1.55 }}>
                  <span className="sl-mono" style={{ color: 'var(--sl-muted)', fontSize: 12 }}>0{i+1}</span>
                  <span>{li}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </article>
    </div>
  );
}

Object.assign(window, { MethodologyPage });
