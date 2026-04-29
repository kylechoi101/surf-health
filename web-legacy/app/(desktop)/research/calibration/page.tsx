import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import Link from 'next/link';
import { EditorialPage } from '@/components/EditorialPage';

function MetricCell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ padding: '20px 24px', background: 'var(--sl-ecru)', border: '1px solid var(--sl-line-soft)', borderRadius: 12 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)' }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 26, color: 'var(--sl-navy-ink)', marginTop: 8 }}>{value}</div>
      {sub && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--sl-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default async function CalibrationPage() {
  let health: Record<string, any> = {};
  try {
    const healthPath = path.join(process.cwd(), '../data/curated/system_health.json');
    health = JSON.parse(await fs.readFile(healthPath, 'utf8'));
  } catch {}

  const reg = health.model_registry ?? {};
  const prodModel: string = reg.production_model ?? '—';
  const prodMetrics: Record<string, number> = reg.production_metrics ?? {};
  const valMetrics: Record<string, number> = reg.temporal_validation_metrics ?? reg.validation_metrics ?? {};
  const spatialMetrics: Record<string, Record<string, number>> = reg.spatial_metrics ?? {};
  const candidates: string[] = reg.candidate_models ?? [];
  const isEligible: boolean = reg.public_release_eligible ?? false;
  const promotionBlockers: string[] = reg.promotion_blockers ?? [];

  const fmt = (v: number | undefined) => v != null ? v.toFixed(4) : '—';
  const fmtPct = (v: number | undefined) => v != null ? `${(v * 100).toFixed(1)}%` : '—';

  return (
    <EditorialPage>
      <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>

        <div style={{ marginBottom: 12 }}>
          <Link href="/research" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', textDecoration: 'none', letterSpacing: '0.08em' }}>
            ← Research
          </Link>
        </div>

        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
          Research · Calibration
        </div>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 80, marginTop: 18, marginBottom: 32, fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)', maxWidth: 900 }}>
          Model performance<br/>& validation.
        </h1>
        <p style={{ fontFamily: 'var(--font-text)', fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 680, margin: 0 }}>
          All metrics on this page are read directly from the daily pipeline output. Spatial
          backtests use county-level GroupKFold holdout; the persistence baseline gives a lower
          bound on skill.
        </p>

        {/* Production model strip */}
        <div style={{ marginTop: 56, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, padding: '28px 32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 40, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)' }}>Production model</div>
              <div style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy-ink)', fontWeight: 400, marginTop: 6 }}>{prodModel}</div>
            </div>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
              <div style={{
                background: isEligible ? 'var(--sl-risk-low-bg)' : 'var(--sl-risk-high-bg)',
                color: isEligible ? 'var(--sl-risk-low-ink)' : 'var(--sl-risk-high-ink)',
                fontFamily: 'var(--font-mono)', fontSize: 11, padding: '6px 14px', borderRadius: 20,
              }}>
                {isEligible ? 'Public release eligible' : 'Blocked'}
              </div>
              {promotionBlockers.length > 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>
                  {promotionBlockers.join(', ')}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Production + validation metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 64, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 01</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>METRICS</div>
          </aside>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 36, margin: '0 0 24px', fontWeight: 400, letterSpacing: '-0.01em', color: 'var(--sl-navy-ink)' }}>
              Discrimination &amp; calibration scores.
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
              <MetricCell label="Production AUCPR" value={fmt(prodMetrics.aucpr)} sub="holdout test set" />
              <MetricCell label="Production Brier" value={fmt(prodMetrics.brier)} sub="lower is better" />
              <MetricCell label="Temporal val AUCPR" value={fmt(valMetrics.aucpr)} sub="time-blocked CV" />
              <MetricCell label="Temporal val Brier" value={fmt(valMetrics.brier)} sub="time-blocked CV" />
            </div>
            <div style={{ padding: '16px 20px', background: 'var(--sl-bone)', borderRadius: 10, border: '1px solid var(--sl-line)', fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-muted)', lineHeight: 1.6, maxWidth: 680 }}>
              <strong style={{ color: 'var(--sl-ink)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>AUCPR baseline</strong> — the persistence model (yesterday&apos;s result as today&apos;s prediction) scores ≈ 0.22–0.25 at a 17–21% exceedance base rate. The production model must clear this by a statistically significant margin under the block-bootstrap gate.
            </div>
          </div>
        </div>

        {/* Spatial backtest */}
        {Object.keys(spatialMetrics).length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
            marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
            <aside>
              <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 02</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>SPATIAL BACKTESTS</div>
            </aside>
            <div>
              <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 36, margin: '0 0 8px', fontWeight: 400, letterSpacing: '-0.01em', color: 'var(--sl-navy-ink)' }}>
                Performance on unseen geography.
              </h2>
              <p style={{ fontFamily: 'var(--font-text)', fontSize: 15, color: 'var(--sl-muted)', lineHeight: 1.6, margin: '0 0 28px', maxWidth: 640 }}>
                County GroupKFold holdout: each fold withholds all beaches from one county. Tests generalisation to locations not seen during training.
              </p>
              <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 100px 100px 80px 80px 100px', padding: '12px 22px', borderBottom: '1px solid var(--sl-line)', fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)', fontWeight: 600 }}>
                  <span>Model</span><span>AUCPR</span><span>Brier</span><span>Folds</span><span>Rows</span><span>Base rate</span>
                </div>
                {Object.entries(spatialMetrics).map(([name, m], i, arr) => (
                  <div key={name} style={{ display: 'grid', gridTemplateColumns: '2fr 100px 100px 80px 80px 100px', padding: '16px 22px', borderBottom: i < arr.length - 1 ? '1px solid var(--sl-line-soft)' : 'none', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-ink)' }}>{name.replace(/_/g, ' ')}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--sl-navy-ink)' }}>{fmt(m.aucpr)}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--sl-navy-ink)' }}>{fmt(m.brier)}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--sl-muted)' }}>{m.folds ?? '—'}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--sl-muted)' }}>{m.heldout_rows ? Math.round(m.heldout_rows) : '—'}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--sl-muted)' }}>{fmtPct(m.positive_rate)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Candidate models */}
        {candidates.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
            marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
            <aside>
              <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 03</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>CANDIDATE MODELS</div>
            </aside>
            <div>
              <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 36, margin: '0 0 20px', fontWeight: 400, letterSpacing: '-0.01em', color: 'var(--sl-navy-ink)' }}>
                Models evaluated each CI run.
              </h2>
              <p style={{ fontFamily: 'var(--font-text)', fontSize: 15, color: 'var(--sl-muted)', lineHeight: 1.6, margin: '0 0 24px', maxWidth: 640 }}>
                All candidates must clear the block-bootstrap AUCPR gate to be eligible for production. The temporal validation winner becomes production if it also clears the spatial backtest promotion policy.
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {candidates.map(c => (
                  <span key={c} style={{
                    fontFamily: 'var(--font-mono)', fontSize: 12, padding: '8px 16px',
                    borderRadius: 8, border: '1px solid var(--sl-line)',
                    background: c === prodModel ? 'var(--sl-navy)' : 'var(--sl-bone)',
                    color: c === prodModel ? 'var(--sl-bone)' : 'var(--sl-ink)',
                  }}>
                    {c}{c === prodModel ? ' ★' : ''}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Methodology link */}
        <div style={{ marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Full evaluation protocol</div>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 22, color: 'var(--sl-navy)', fontWeight: 400 }}>Technical Methodology</div>
            <div style={{ fontFamily: 'var(--font-text)', fontSize: 14, color: 'var(--sl-muted)', marginTop: 4 }}>Spatial CV protocol, promotion gates, and feature rationale.</div>
          </div>
          <Link href="/methodology" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-navy)', textDecoration: 'none', border: '1px solid var(--sl-line)', padding: '10px 18px', borderRadius: 8, background: 'var(--sl-ecru)', whiteSpace: 'nowrap' }}>
            Read methodology →
          </Link>
        </div>

      </article>
    </EditorialPage>
  );
}
