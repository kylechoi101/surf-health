import React from 'react';
import Link from 'next/link';
import { RiskChip, DropRow } from '@/components/RiskComponents';
import { RISK_ORDER, RISK_COPY } from '@/lib/riskData';
import { EditorialPage } from '@/components/EditorialPage';

const BAND_DETAIL: Record<string, { threshold: string; action: string; legal: string }> = {
  Low: {
    threshold: 'Predicted exceedance probability < 15 %',
    action: 'Water is suitable for body-contact recreation.',
    legal: 'Below EPA STV (104 CFU/100mL) and state action threshold.',
  },
  Moderate: {
    threshold: 'Predicted exceedance probability 15–35 %',
    action: 'Avoid swallowing water; rinse thoroughly after exit.',
    legal: 'Elevated but below the single-sample violation threshold.',
  },
  High: {
    threshold: 'Predicted exceedance probability 35–65 %',
    action: 'Avoid water contact, especially for sensitive groups.',
    legal: 'Exceeds 104 CFU/100mL with high probability; county may post advisory.',
  },
  'Very High': {
    threshold: 'Predicted exceedance probability > 65 %',
    action: 'Stay out of water. Check posted county advisory.',
    legal: 'Model predicts likely ≥ 320 CFU/100mL; corresponds to CDPH closure threshold.',
  },
};

export default function LabelsPage() {
  return (
    <EditorialPage>
      <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>

        <div style={{ marginBottom: 12 }}>
          <Link href="/research" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', textDecoration: 'none', letterSpacing: '0.08em' }}>
            ← Research
          </Link>
        </div>

        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
          Research · Labels
        </div>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 80, marginTop: 18, marginBottom: 32, fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)', maxWidth: 900 }}>
          How risk bands<br/>are defined.
        </h1>
        <p style={{ fontFamily: 'var(--font-text)', fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 680, margin: 0 }}>
          Each beach is assigned one of four risk bands derived from the model&apos;s calibrated
          exceedance probability — the chance that enterococcus exceeds the EPA single-sample
          threshold of 104 CFU/100mL on a given day.
        </p>

        {/* Threshold logic */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 01</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>THRESHOLDS</div>
          </aside>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 24px', fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)' }}>
              From probability to label.
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
              {[
                ['EPA STV', 'The single-sample threshold for enterococcus in marine waters is 104 CFU/100mL (EPA Recreational Water Quality Criteria, 2012). Exceeding this value does not guarantee illness but indicates elevated risk.'],
                ['Calibrated probability', 'The model outputs a calibrated p_exceed — the estimated probability that the true concentration will exceed 104 CFU/100mL on the forecast day, given environmental covariates.'],
                ['Band cut-points', 'Cut-points (15 %, 35 %, 65 %) are tuned so false negatives (missed High/Very High days) are penalised more heavily than false positives in the loss function, providing a conservative public-health posture.'],
                ['County advisories', 'Shorelife bands are forecasts; official CDPH/county advisories are posted after a confirmed sample violation. A Very High forecast does not replace a posted advisory.'],
              ].map(([h, b]) => (
                <div key={h} style={{ paddingTop: 20, borderTop: '1px solid var(--sl-line-soft)' }}>
                  <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 22, margin: '0 0 10px', color: 'var(--sl-navy)', fontWeight: 400 }}>{h}</h3>
                  <p style={{ fontFamily: 'var(--font-text)', fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.65, margin: 0 }}>{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Band definitions */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 02</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>BAND DEFINITIONS</div>
          </aside>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 28px', fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)' }}>
              Four levels, calibrated for public health.
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, overflow: 'hidden' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 1.4fr 1fr', padding: '14px 24px', borderBottom: '1px solid var(--sl-line)', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--sl-muted)', fontWeight: 600 }}>
                <span>Band</span><span>Guidance</span><span>Probability gate</span><span>Action</span>
              </div>
              {RISK_ORDER.map((band) => {
                const c = RISK_COPY[band];
                const d = BAND_DETAIL[band];
                return (
                  <div key={band} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 1.4fr 1fr', padding: '22px 24px', borderBottom: band === 'Very High' ? 'none' : '1px solid var(--sl-line-soft)', alignItems: 'start', gap: 16 }}>
                    <div>
                      <RiskChip band={band} />
                      <div style={{ marginTop: 8 }}><DropRow band={band} size={10} /></div>
                    </div>
                    <div>
                      <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18, color: 'var(--sl-navy)', fontWeight: 400, marginBottom: 4 }}>{c.head}</div>
                      <div style={{ fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-ink)', lineHeight: 1.5 }}>{c.sub}</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 6 }}>{c.cfu} CFU/100mL</div>
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-ink)', lineHeight: 1.6 }}>{d.threshold}</div>
                    <div style={{ fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-ink)', lineHeight: 1.55 }}>{d.action}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Legal / statutory note */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-risk-vh)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 03</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>LEGAL BASIS</div>
          </aside>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 40, margin: '0 0 24px', fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)' }}>
              What the model can and cannot do.
            </h2>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 0 }}>
              {[
                'Shorelife forecasts are probabilistic estimates, not certified sample results.',
                'Official beach closures and advisories are issued by county environmental health agencies under California AB 411.',
                'A Low band forecast does not guarantee safe water. Localised events (sewage spills, storm runoff) can override model predictions.',
                'The model is trained exclusively on marine enterococcus (culture-based, MPN/IDEXX). Freshwater E. coli and other analytes are outside its scope.',
                'For confirmed regulatory status, always consult the current county health advisory for the specific beach.',
              ].map((li, i) => (
                <li key={i} style={{ display: 'flex', gap: 16, paddingTop: 16, paddingBottom: 16, borderTop: '1px dashed var(--sl-line)', fontSize: 15, color: 'var(--sl-ink)', lineHeight: 1.6, fontFamily: 'var(--font-text)' }}>
                  <span style={{ color: 'var(--sl-muted)', fontSize: 11, fontFamily: 'var(--font-mono)', minWidth: 20 }}>0{i + 1}</span>
                  <span>{li}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

      </article>
    </EditorialPage>
  );
}
