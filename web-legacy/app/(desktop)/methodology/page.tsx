import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import { RiskChip, DropRow } from '@/components/RiskComponents';
import { RISK_ORDER, RISK_COPY } from '@/lib/riskData';
import { EditorialPage } from '@/components/EditorialPage';

export default async function MethodologyPage() {
  let versionLabel = 'v1.5';
  let dateLabel = 'Apr 2026';
  try {
    const mvPath = path.join(process.cwd(), '../data/curated/model_version.json');
    const mv = JSON.parse(await fs.readFile(mvPath, 'utf8'));
    if (mv.ship_target) versionLabel = mv.ship_target;
    if (mv.promoted_at) {
      const d = new Date(mv.promoted_at);
      dateLabel = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
  } catch {}

  return (
    <EditorialPage>
    <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>
      <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>{`Methodology · ${versionLabel} · ${dateLabel}`}</div>
      <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 96, marginTop: 18, marginBottom: 32, fontWeight: 400, letterSpacing: '-0.02em',
        color: 'var(--sl-navy-ink)', maxWidth: 980 }}>
        How the forecast<br/>is built.
      </h1>
      <p style={{ fontFamily: 'var(--font-text)', fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 720, margin: 0 }}>
        Shorelife models marine enterococcus risk using official California sample history and daily
        environmental context from nearshore ocean and weather sources. We publish a calibrated
        exceedance probability, banded into four public-facing risk levels.
      </p>

      {/* Two-column editorial */}
      <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
        marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
        <aside>
          <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 01</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)',
            marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>
            MODEL DESIGN
          </div>
        </aside>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 24px', fontWeight: 400, letterSpacing: '-0.02em',
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
                <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 22, margin: '0 0 10px', color: 'var(--sl-navy)', fontWeight: 400 }}>{h}</h3>
                <p style={{ fontFamily: 'var(--font-text)', fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.65, margin: 0 }}>{b}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Risk band table */}
      <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
        marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
        <aside>
          <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 02</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)',
            marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>
            RISK BANDS
          </div>
        </aside>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 28px', fontWeight: 400, letterSpacing: '-0.02em',
            color: 'var(--sl-navy-ink)' }}>
            Four bands, calibrated for public alerts.
          </h2>
          <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
            borderRadius: 14, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr 80px',
              padding: '14px 22px', borderBottom: '1px solid var(--sl-line)',
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.14em',
              textTransform: 'uppercase', color: 'var(--sl-muted)', fontWeight: 600 }}>
              <span>Band</span><span>Headline</span><span>Guidance</span><span>Enterococcus</span><span>Drops</span>
            </div>
            {RISK_ORDER.map((band) => {
              const c = RISK_COPY[band];
              if (!c) return null;
              return (
                <div key={band} style={{
                  display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr 80px',
                  padding: '20px 22px', alignItems: 'center',
                  borderBottom: band === 'Very High' ? 'none' : '1px solid var(--sl-line-soft)',
                }}>
                  <span><RiskChip band={band}/></span>
                  <span style={{ fontFamily: 'var(--font-heading)', fontSize: 22, color: 'var(--sl-navy)', fontWeight: 400 }}>{c.head}</span>
                  <span style={{ fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-ink)', lineHeight: 1.5 }}>{c.sub}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-ink)' }}>{c.cfu}</span>
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
          <div style={{ color: 'var(--sl-risk-vh)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 03</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)',
            marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>
            LIMITS
          </div>
        </aside>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 24px', fontWeight: 400, letterSpacing: '-0.02em',
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
                color: 'var(--sl-ink)', lineHeight: 1.55, fontFamily: 'var(--font-text)' }}>
                <span style={{ color: 'var(--sl-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>0{i+1}</span>
                <span>{li}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Model Card Link */}
      <div style={{ marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Full specification</div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 22, color: 'var(--sl-navy)', fontWeight: 400 }}>Model Card</div>
          <div style={{ fontFamily: 'var(--font-text)', fontSize: 14, color: 'var(--sl-muted)', marginTop: 4 }}>Feature rationale, spatial CV protocol, and known failure modes.</div>
        </div>
        <a
          href="https://github.com/kylechoi101/surf-health/blob/main/data/curated/model_card.md"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-navy)', textDecoration: 'none', border: '1px solid var(--sl-line)', padding: '10px 18px', borderRadius: 8, background: 'var(--sl-ecru)', whiteSpace: 'nowrap' }}
        >
          Read model card →
        </a>
      </div>

      {/* References */}
      <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
        marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
        <aside>
          <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 04</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)',
            marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>
            REFERENCES
          </div>
        </aside>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 28px', fontWeight: 400, letterSpacing: '-0.02em',
            color: 'var(--sl-navy-ink)' }}>
            Sources and prior work.
          </h2>
          <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 0 }}>
            {[
              {
                n: 1,
                text: 'Searcy, R. T. & Boehm, A. B. (2021). A day at the beach: enabling coastal water quality prediction with high-frequency sampling and machine learning.',
                url: 'https://doi.org/10.1016/j.watres.2021.117051',
                label: 'Water Research · DOI: 10.1016/j.watres.2021.117051',
              },
              {
                n: 2,
                text: 'U.S. EPA. Virtual Beach 3 (VB3): User Guide. Enterococcus-based per-station MLR as production baseline.',
                url: 'https://www.epa.gov/exposure-assessment-models/virtual-beach-vb',
                label: 'EPA VB3 Reference Manual',
              },
              {
                n: 3,
                text: 'California Department of Public Health. AB411 Annual Beach Report. County advisory thresholds and official culture-based sampling protocol.',
                url: 'https://www.cdph.ca.gov/Programs/CEH/DRSEM/Pages/BeachMonitoring.aspx',
                label: 'CDPH AB411 / Beach Monitoring Program',
              },
              {
                n: 4,
                text: 'NOAA National Data Buoy Center (NDBC). Real-time and historical wave, wind, and sea surface temperature observations used as model covariates.',
                url: 'https://www.ndbc.noaa.gov',
                label: 'NDBC · noaa.gov/ndbc',
              },
              {
                n: 5,
                text: 'Scripps Institution of Oceanography. Coastal Data Information Program (CDIP). Nearshore wave model output and buoy telemetry.',
                url: 'https://cdip.ucsd.edu',
                label: 'CDIP · cdip.ucsd.edu',
              },
              {
                n: 6,
                text: 'Open-Meteo. Open-source weather API — hourly UV index and solar radiation used for solar inactivation index feature.',
                url: 'https://open-meteo.com',
                label: 'Open-Meteo API · open-meteo.com',
              },
            ].map(ref => (
              <li key={ref.n} style={{ display: 'flex', gap: 20, paddingTop: 20, paddingBottom: 20,
                borderTop: '1px solid var(--sl-line-soft)', fontSize: 14,
                color: 'var(--sl-ink)', lineHeight: 1.6, fontFamily: 'var(--font-text)' }}>
                <span style={{ color: 'var(--sl-muted)', fontSize: 11, fontFamily: 'var(--font-mono)', minWidth: 20, paddingTop: 2 }}>[{ref.n}]</span>
                <span>
                  {ref.text}{' '}
                  <a href={ref.url} target="_blank" rel="noopener noreferrer"
                    style={{ color: 'var(--sl-navy)', textDecoration: 'none', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    {ref.label} ↗
                  </a>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </article>
    </EditorialPage>
  );
}