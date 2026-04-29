import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import Link from 'next/link';

interface SourceDef {
  name: string;
  org: string;
  what: string;
  fields: string[];
  freq: string;
  url: string;
  freshness_key?: string;
}

const SOURCES: SourceDef[] = [
  {
    name: 'CA BeachWatch',
    org: 'CDPH / County Health',
    what: 'Official marine enterococcus culture-based sample results, beach advisory status (active/closed/precautionary), and historical AB 411 records.',
    fields: ['enterococcus CFU/100mL', 'advisory type', 'advisory start/end', 'sample station ID'],
    freq: 'Daily (Mon–Fri in-season); batch-ingested each morning',
    url: 'https://data.ca.gov/dataset/beach-monitoring',
    freshness_key: 'beaches',
  },
  {
    name: 'NDBC Buoy Network',
    org: 'NOAA NDBC',
    what: 'Hourly ocean observations from nearshore buoys: significant wave height, dominant period, sea-surface temperature, salinity, and wind.',
    fields: ['wave_height_m', 'dominant_period_s', 'water_temperature_c', 'salinity_psu', 'wind_speed_mps'],
    freq: 'Hourly; aggregated to daily forecast-safe windows (≤ 5 AM PT)',
    url: 'https://www.ndbc.noaa.gov',
    freshness_key: 'observations',
  },
  {
    name: 'CDIP Wave Model',
    org: 'Scripps Institution of Oceanography',
    what: 'Nearshore wave model output and buoy telemetry at California coastal sites, used to supplement NDBC coverage.',
    fields: ['Hs', 'Tp', 'wave direction'],
    freq: 'Hourly; aggregated daily',
    url: 'https://cdip.ucsd.edu',
  },
  {
    name: 'Open-Meteo ERA5-Land',
    org: 'Open-Meteo / ECMWF',
    what: 'Reanalysis archive of hourly cloud cover, shortwave radiation, UV index, and near-surface wind at 0.1° resolution. Used for solar inactivation and wind plume features.',
    fields: ['uv_index', 'shortwave_radiation', 'cloud_cover', 'wind_u', 'wind_v', 'solar_inactivation_index', 'shore_normal_wind_ms'],
    freq: 'Backfill on first run (6-year archive); then daily append. Cached per (lat, lon, date) parquet.',
    url: 'https://open-meteo.com',
  },
  {
    name: 'USGS NWIS',
    org: 'USGS National Water Information System',
    what: 'Daily streamflow and gage-height records for rivers and creeks draining to monitored beaches. Used as hydrology covariate proxying storm-runoff pollution.',
    fields: ['discharge_cfs', 'gage_height_ft'],
    freq: 'Daily; lag-adjusted (1–3 day lag to beach)',
    url: 'https://waterdata.usgs.gov/nwis',
  },
  {
    name: 'CEDEN',
    org: 'CA SWRCB',
    what: 'California Environmental Data Exchange Network — additional water quality measurements used to supplement BeachWatch gaps.',
    fields: ['enterococcus', 'E. coli (excluded from model labels)', 'total coliform (excluded)'],
    freq: 'Bulk pull (≤ 50,000 rows); merged at pipeline init',
    url: 'https://ceden.waterboards.ca.gov',
  },
];

export default async function SourcesPage() {
  let sourceFreshness: Record<string, string> = {};
  let pipelineFreshness = '';
  try {
    const healthPath = path.join(process.cwd(), '../data/curated/system_health.json');
    const h = JSON.parse(await fs.readFile(healthPath, 'utf8'));
    sourceFreshness = h.source_freshness ?? {};
    pipelineFreshness = h.pipeline_freshness ?? '';
  } catch {}

  const fmtAge = (iso: string) => {
    if (!iso) return '—';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 60) return `${min}m ago`;
    if (min < 1440) return `${Math.round(min / 60)}h ago`;
    return `${Math.round(min / 1440)}d ago`;
  };

  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-4">
          <Link href="/research" className="font-mono text-[11px] text-muted-foreground hover:text-foreground transition-colors tracking-widest">
            ← Research
          </Link>
        </div>

        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Research · Sources
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          Where the data<br/>comes from.
        </h1>
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-14">
          Shorelife integrates six primary data sources, all public or government-archived, into a
          daily pipeline that runs at 6 AM PT. Each source is attributed in the model feature space
          and versioned in the parquet archive.
        </p>

        {/* Freshness strip */}
        {pipelineFreshness && (
          <div className="mt-14 bg-muted/30 border border-border/50 rounded-2xl p-7 md:p-8 flex flex-col sm:flex-row gap-10 sm:gap-16 items-start sm:items-center flex-wrap mb-24">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Pipeline heartbeat</div>
              <div className="font-mono text-xl text-foreground mt-2">{fmtAge(pipelineFreshness)}</div>
            </div>
            {Object.entries(sourceFreshness).map(([k, v]) => (
              <div key={k}>
                <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{k}</div>
                <div className="font-mono text-xl text-foreground mt-2">{fmtAge(v)}</div>
              </div>
            ))}
          </div>
        )}

        {/* Sources grid */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 01</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Data Sources</div>
          </aside>
          <div className="flex flex-col gap-12">
            {SOURCES.map((s, i) => (
              <div key={s.name} className={`pt-8 ${i === 0 ? '' : 'border-t border-border/50'} grid lg:grid-cols-[1fr_1.4fr] gap-10`}>
                <div>
                  <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{s.org}</div>
                  <div className="text-3xl font-light text-foreground mt-2 mb-3">{s.name}</div>
                  {s.freshness_key && sourceFreshness[s.freshness_key] && (
                    <div className="inline-block bg-emerald-500/10 text-emerald-600 font-mono text-[10px] uppercase tracking-widest px-3 py-1 rounded-full mb-6">
                      Last seen {fmtAge(sourceFreshness[s.freshness_key])}
                    </div>
                  )}
                  <div className={s.freshness_key && sourceFreshness[s.freshness_key] ? "" : "mt-6"}>
                    <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Update cadence</div>
                    <div className="text-sm text-foreground mt-1.5 leading-relaxed">{s.freq}</div>
                    <a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-block mt-4 font-mono text-[11px] tracking-widest text-primary border-b border-border/50 hover:border-primary transition-colors pb-0.5">
                      {s.url.replace('https://', '')} ↗
                    </a>
                  </div>
                </div>
                <div>
                  <p className="text-base text-foreground leading-relaxed mb-6">{s.what}</p>
                  <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-3">Fields used</div>
                  <div className="flex flex-wrap gap-2">
                    {s.fields.map(f => (
                      <span key={f} className="bg-muted/30 border border-border/50 font-mono text-[11px] px-3 py-1 rounded-md text-foreground">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Pipeline note */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 02</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Pipeline</div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-6 text-foreground">
              Forecast-safe cutoff at 5 AM PT.
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl mb-8">
              The pipeline runs daily at 6 AM PT. All environmental covariates are summarised up to
              5 AM PT of the forecast day so no same-morning laboratory results leak into the
              features. Open-Meteo data is cached per (lat, lon, date) in a local parquet store
              and incrementally updated; a full 6-year backfill runs only on the first cold-cache
              CI run.
            </p>
            <a href="https://github.com/kylechoi101/surf-health/blob/main/CLAUDE.md" target="_blank" rel="noopener noreferrer"
              className="inline-block font-mono text-[11px] tracking-widest uppercase px-5 py-2.5 bg-muted/30 border border-border/50 rounded-lg text-primary hover:text-primary/80 transition-colors">
              Pipeline reference →
            </a>
          </div>
        </div>

      </article>
    </main>
  );
}
