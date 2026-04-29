import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import Link from 'next/link';

function MetricCell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="p-5 bg-muted/30 border border-border/50 rounded-xl">
      <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="font-mono text-2xl text-foreground mt-2">{value}</div>
      {sub && <div className="font-mono text-[10px] text-muted-foreground mt-1">{sub}</div>}
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
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-4">
          <Link href="/research" className="font-mono text-[11px] text-muted-foreground hover:text-foreground transition-colors tracking-widest">
            ← Research
          </Link>
        </div>

        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Research · Calibration
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          Model performance<br/>& validation.
        </h1>
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-14">
          All metrics on this page are read directly from the daily pipeline output. Spatial
          backtests use county-level GroupKFold holdout; the persistence baseline gives a lower
          bound on skill.
        </p>

        {/* Production model strip */}
        <div className="mt-14 bg-muted/30 border border-border/50 rounded-2xl p-7 md:p-8 mb-24">
          <div className="flex flex-col sm:flex-row justify-between items-start gap-10">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Production model</div>
              <div className="text-3xl font-light text-foreground mt-2">{prodModel}</div>
            </div>
            <div className="flex gap-4 items-center flex-wrap">
              <div className={`font-mono text-[11px] px-3.5 py-1.5 rounded-full ${
                isEligible ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600'
              }`}>
                {isEligible ? 'Public release eligible' : 'Blocked'}
              </div>
              {promotionBlockers.length > 0 && (
                <div className="font-mono text-[11px] text-muted-foreground">
                  {promotionBlockers.join(', ')}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Production + validation metrics */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 01</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Metrics</div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              Discrimination &amp; calibration scores.
            </h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <MetricCell label="Production AUCPR" value={fmt(prodMetrics.aucpr)} sub="holdout test set" />
              <MetricCell label="Production Brier" value={fmt(prodMetrics.brier)} sub="lower is better" />
              <MetricCell label="Temporal val AUCPR" value={fmt(valMetrics.aucpr)} sub="time-blocked CV" />
              <MetricCell label="Temporal val Brier" value={fmt(valMetrics.brier)} sub="time-blocked CV" />
            </div>
            <div className="p-5 bg-muted/30 rounded-xl border border-border/50 text-sm text-muted-foreground leading-relaxed">
              <strong className="text-foreground font-mono text-[11px] mr-1">AUCPR baseline</strong> 
              — the persistence model (yesterday&apos;s result as today&apos;s prediction) scores ≈ 0.22–0.25 at a 17–21% exceedance base rate. The production model must clear this by a statistically significant margin under the block-bootstrap gate.
            </div>
          </div>
        </div>

        {/* Spatial backtest */}
        {Object.keys(spatialMetrics).length > 0 && (
          <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
            <aside>
              <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 02</div>
              <div className="text-xs text-muted-foreground tracking-wider uppercase">Spatial Backtests</div>
            </aside>
            <div>
              <h2 className="text-3xl font-light mb-4 text-foreground">
                Performance on unseen geography.
              </h2>
              <p className="text-base text-muted-foreground leading-relaxed mb-8 max-w-2xl">
                County GroupKFold holdout: each fold withholds all beaches from one county. Tests generalisation to locations not seen during training.
              </p>
              <div className="bg-muted/30 border border-border/50 rounded-2xl overflow-hidden overflow-x-auto">
                <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] p-4 border-b border-border/50 font-mono text-[10px] uppercase tracking-widest text-muted-foreground font-semibold min-w-[600px]">
                  <span>Model</span><span>AUCPR</span><span>Brier</span><span>Folds</span><span>Rows</span><span>Base rate</span>
                </div>
                {Object.entries(spatialMetrics).map(([name, m], i, arr) => (
                  <div key={name} className={`grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] p-4 items-center min-w-[600px] ${i < arr.length - 1 ? 'border-b border-border/50' : ''}`}>
                    <span className="font-mono text-xs text-foreground">{name.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-sm text-foreground">{fmt(m.aucpr)}</span>
                    <span className="font-mono text-sm text-foreground">{fmt(m.brier)}</span>
                    <span className="font-mono text-xs text-muted-foreground">{m.folds ?? '—'}</span>
                    <span className="font-mono text-xs text-muted-foreground">{m.heldout_rows ? Math.round(m.heldout_rows) : '—'}</span>
                    <span className="font-mono text-xs text-muted-foreground">{fmtPct(m.positive_rate)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Candidate models */}
        {candidates.length > 0 && (
          <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
            <aside>
              <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 03</div>
              <div className="text-xs text-muted-foreground tracking-wider uppercase">Candidate Models</div>
            </aside>
            <div>
              <h2 className="text-3xl font-light mb-6 text-foreground">
                Models evaluated each CI run.
              </h2>
              <p className="text-base text-muted-foreground leading-relaxed mb-8 max-w-2xl">
                All candidates must clear the block-bootstrap AUCPR gate to be eligible for production. The temporal validation winner becomes production if it also clears the spatial backtest promotion policy.
              </p>
              <div className="flex flex-wrap gap-3">
                {candidates.map(c => (
                  <span key={c} className={`font-mono text-xs px-4 py-2 rounded-lg border border-border/50 ${
                    c === prodModel ? 'bg-foreground text-background' : 'bg-muted/30 text-foreground'
                  }`}>
                    {c}{c === prodModel ? ' ★' : ''}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Methodology link */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-6 pt-12 border-t border-border/50">
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-widest mb-2">Full evaluation protocol</div>
            <div className="text-2xl font-light text-foreground mb-1">Technical Methodology</div>
            <div className="text-sm text-muted-foreground">Spatial CV protocol, promotion gates, and feature rationale.</div>
          </div>
          <Link href="/methodology" className="text-sm font-medium text-primary hover:text-primary/80 px-6 py-3 border border-border/50 rounded-sm bg-muted/30 transition-colors whitespace-nowrap">
            Read methodology →
          </Link>
        </div>

      </article>
    </main>
  );
}
