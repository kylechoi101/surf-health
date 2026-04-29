import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import { getBeaches } from '@/lib/api';
import Link from 'next/link';

export default async function ResearchPage() {
  const healthPath = path.join(process.cwd(), '../data/curated/system_health.json');
  const healthData = JSON.parse(await fs.readFile(healthPath, 'utf8'));
  
  const allBeaches = await getBeaches({ cache: 'force-cache' });
  const stations = allBeaches.slice(0, 12);

  const model = healthData.model_registry.production_model;
  const prodMetrics = healthData.model_registry.production_metrics ?? {};
  const testAucpr = prodMetrics.aucpr != null ? prodMetrics.aucpr.toFixed(4) : '—';
  const testBrier = prodMetrics.brier != null ? prodMetrics.brier.toFixed(4) : '—';
  const isEligible = healthData.model_registry.public_release_eligible ? 'Eligible' : 'Blocked';

  const timeSince = (isoString: string) => {
    const min = Math.round((Date.now() - new Date(isoString).getTime()) / 60000);
    if (min < 60) return `${min}m ago`;
    if (min < 1440) return `${Math.round(min/60)}h ago`;
    return `${Math.round(min/1440)}d ago`;
  };

  const sources = [
    ['CA Beach Watch (CDPH)', healthData.source_freshness.beaches],
    ['NDBC buoy network', healthData.source_freshness.observations],
    ['Pipeline heartbeat', healthData.pipeline_freshness],
  ];

  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Research · operator view · build {new Date().toISOString().split('T')[0].replace(/-/g, '.')}
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          Model health &<br/>deployment traceability.
        </h1>
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-14">
          The operator view tracks model registry status, source freshness, and which stations are
          ready for production versus beta fallback.
        </p>

        {/* Registry stats */}
        <div className="mt-14 grid grid-cols-2 md:grid-cols-5 gap-px bg-border/50 border border-border/50 rounded-2xl overflow-hidden mb-24">
          {[
            ['Production model', model, 'font-light text-xl', ''],
            ['Test AUCPR', testAucpr, 'font-mono text-2xl', ''],
            ['Test Brier', testBrier, 'font-mono text-2xl', ''],
            ['Coverage', `${stations.length} / 0`, 'font-mono text-2xl', 'production / beta'],
            ['Public release', isEligible, 'font-light text-xl', ''],
          ].map((r, i) => (
            <div key={i} className="bg-muted/30 p-6 md:p-8 flex flex-col justify-center">
              <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest mb-3">{r[0]}</div>
              <div className={`${r[2]} text-foreground`}>{r[1]}</div>
              {r[3] && <div className="text-[10px] text-muted-foreground font-mono mt-1">{r[3]}</div>}
            </div>
          ))}
        </div>

        {/* Validation / Spatial Metrics */}
        {healthData.model_registry.spatial_metrics && (
          <div className="bg-muted/30 border border-border/50 rounded-2xl p-8 mb-24">
            <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">Spatial backtests</div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              Performance on unobserved counties
            </h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(healthData.model_registry.spatial_metrics).map(([name, m]: [string, any]) => (
                <div key={name} className="bg-background border border-border/50 rounded-xl p-5">
                  <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest mb-4">{name.replace(/_/g, ' ')}</div>
                  <div className="flex justify-between items-end">
                    <div>
                      <div className="text-[10px] text-muted-foreground uppercase font-mono tracking-widest">AUCPR</div>
                      <div className="text-2xl font-mono text-foreground">{m.aucpr.toFixed(3)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] text-muted-foreground uppercase font-mono tracking-widest">Brier</div>
                      <div className="text-2xl font-mono text-foreground">{m.brier.toFixed(3)}</div>
                    </div>
                  </div>
                  <div className="mt-4 pt-4 border-t border-border/50 text-[11px] text-muted-foreground font-mono">
                    {m.folds} folds · {m.heldout_rows} samples
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Research subpages */}
        <div className="mb-24">
          <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">Deep dives</div>
          <h2 className="text-3xl font-light mb-8 text-foreground">
            Transparency documentation
          </h2>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { href: '/research/labels', title: 'Risk Labels', desc: 'How exceedance probability maps to the four public bands, legal basis, and what the model can and cannot predict.', tag: 'Labels · Thresholds' },
              { href: '/research/sources', title: 'Data Sources', desc: 'The six primary datasets feeding the pipeline — BeachWatch, NDBC, CDIP, Open-Meteo, USGS NWIS, and CEDEN — with freshness status.', tag: 'Provenance · Cadence' },
              { href: '/research/calibration', title: 'Calibration', desc: 'Live production metrics, spatial backtest results, and candidate model registry from the latest CI run.', tag: 'AUCPR · Brier · Spatial CV' },
            ].map(({ href, title, desc, tag }) => (
              <div key={href} className="bg-muted/30 border border-border/50 rounded-2xl p-6 md:p-8 flex flex-col justify-between h-full">
                <div className="mb-8">
                  <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest mb-3">{tag}</div>
                  <h3 className="text-2xl font-light mb-3 text-foreground">{title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
                </div>
                <Link href={href} className="self-start text-[11px] font-mono tracking-widest uppercase px-4 py-2 bg-background border border-border/50 rounded-md text-primary hover:text-primary/80 transition-colors">
                  READ →
                </Link>
              </div>
            ))}
          </div>
        </div>

        <div className="mb-12">
          <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">Scientific artifacts</div>
          <h2 className="text-3xl font-light mb-8 text-foreground">
            Open data & methodology
          </h2>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="bg-muted/30 border border-border/50 rounded-2xl p-6 md:p-8 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-6">
              <div>
                <h3 className="text-xl font-light mb-2 text-foreground">Technical Methodology</h3>
                <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                  Model design, risk-band calibration, spatial holdout protocol, and known limitations.
                </p>
                <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest">
                  Shorelife Team
                </div>
              </div>
              <Link href="/methodology" className="shrink-0 text-[11px] font-mono tracking-widest uppercase px-4 py-2 bg-background border border-border/50 rounded-md text-primary hover:text-primary/80 transition-colors">
                READ →
              </Link>
            </div>
            <div className="bg-muted/30 border border-border/50 rounded-2xl p-6 md:p-8 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-6">
              <div>
                <h3 className="text-xl font-light mb-2 text-foreground">Source Code & Data</h3>
                <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                  Full pipeline, training scripts, and curated datasets available on GitHub under an open-source license.
                </p>
                <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest">
                  Automated Pipeline
                </div>
              </div>
              <a href="https://github.com/kylechoi101/surf-health" target="_blank" rel="noopener noreferrer" className="shrink-0 text-[11px] font-mono tracking-widest uppercase px-4 py-2 bg-background border border-border/50 rounded-md text-primary hover:text-primary/80 transition-colors">
                GITHUB →
              </a>
            </div>
          </div>
        </div>
      </article>
    </main>
  );
}
