import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import { siteStats } from '@/lib/curated';

export default async function MethodologyPage() {
  let versionLabel = 'v1.5';
  let dateLabel = 'Apr 2026';
  const stats = siteStats();
  const coveragePct = stats.totalStations > 0
    ? Math.round((stats.modeledStations / stats.totalStations) * 100)
    : 0;
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
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          {`Methodology · ${versionLabel} · ${dateLabel}`}
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          How the forecast<br/>is built.
        </h1>
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-24">
          Shorelife publishes a daily marine enterococcus forecast using official California sample
          history and nearshore ocean and weather context. Today&apos;s public release covers
          {' '}{stats.modeledStations} of {stats.totalStations} monitored stations ({coveragePct}% coverage);
          unsupported stations stay neutral and point back to the latest official sample instead of
          claiming model confidence.
        </p>

        {/* Two-column editorial */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 01</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">
              Model Design
            </div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              Numerically grounded by default.
            </h2>
            <div className="grid sm:grid-cols-2 gap-8">
              {[
                ['Label policy', 'V1 uses culture-based marine enterococcus only. Freshwater E. coli, total coliform, fecal coliform, and ddPCR stay in the warehouse but outside the pooled forecast label.'],
                ['Daily forecast', 'The pipeline refreshes once each morning. It is a batch forecast that cannot react to an intra-day spill after publication.'],
                ['Baselines first', 'Persistence, logistic/linear, and gradient-boosted tree baselines are mandatory. The neural model stays research-only until it clears blocked-time and explicit spatial holdout gates.'],
                ['Calibration', 'Public-facing bands come from calibrated exceedance probabilities. Unsupported stations do not receive a colored risk claim or a fallback model badge on public surfaces.'],
              ].map(([h, b]) => (
                <div key={h} className="pt-6 border-t border-border/50">
                  <h3 className="text-lg font-medium mb-3 text-foreground">{h}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Caveats */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-red-500 font-medium tracking-widest text-sm uppercase mb-2">§ 02</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">
              Limits
            </div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              What this model can&apos;t do.
            </h2>
            <ul className="space-y-6">
              {[
                'Forecasts complement official monitoring; they do not replace county advisories.',
                'Only a subset of beaches currently has model coverage; the rest should be read as latest-official-sample views, not forecast gaps filled by guesswork.',
                'Heavy storm, sewage, or spill events can outrun any historical statistical model, especially after the morning publish cutoff.',
                'LLM explanations summarize the forecast; the numeric risk comes from the ML model.',
              ].map((li, i) => (
                <li key={i} className="flex gap-4 pt-6 border-t border-dashed border-border/50 text-base text-muted-foreground leading-relaxed">
                  <span className="text-xs font-mono text-muted-foreground pt-1">0{i+1}</span>
                  <span>{li}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Model Card Link */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-6 pt-12 border-t border-border/50 mb-24">
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-widest mb-2">Full specification</div>
            <div className="text-2xl font-light text-foreground mb-1">Model Card</div>
            <div className="text-sm text-muted-foreground">Feature rationale, spatial CV protocol, and known failure modes.</div>
          </div>
          <a
            href="https://github.com/kylechoi101/surf-health/blob/main/data/curated/model_card.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-primary hover:text-primary/80 px-6 py-3 border border-border/50 rounded-sm bg-muted/30 transition-colors whitespace-nowrap"
          >
            Read model card →
          </a>
        </div>

        {/* References */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 03</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">
              References
            </div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              Sources and prior work.
            </h2>
            <ol className="flex flex-col">
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
                <li key={ref.n} className="flex gap-6 py-6 border-t border-border/50 text-sm text-muted-foreground leading-relaxed">
                  <span className="text-xs font-mono pt-1">[{ref.n}]</span>
                  <span>
                    {ref.text}{' '}
                    <a href={ref.url} target="_blank" rel="noopener noreferrer"
                      className="text-primary hover:underline text-xs font-mono ml-2">
                      {ref.label} ↗
                    </a>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </article>
    </main>
  );
}
