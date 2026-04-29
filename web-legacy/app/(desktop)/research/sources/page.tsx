import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import Link from 'next/link';
import { EditorialPage } from '@/components/EditorialPage';

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
    <EditorialPage>
      <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>

        <div style={{ marginBottom: 12 }}>
          <Link href="/research" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', textDecoration: 'none', letterSpacing: '0.08em' }}>
            ← Research
          </Link>
        </div>

        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
          Research · Sources
        </div>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 80, marginTop: 18, marginBottom: 32, fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)', maxWidth: 900 }}>
          Where the data<br/>comes from.
        </h1>
        <p style={{ fontFamily: 'var(--font-text)', fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 680, margin: 0 }}>
          Shorelife integrates six primary data sources, all public or government-archived, into a
          daily pipeline that runs at 6 AM PT. Each source is attributed in the model feature space
          and versioned in the parquet archive.
        </p>

        {/* Freshness strip */}
        {pipelineFreshness && (
          <div style={{ marginTop: 48, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 12, padding: '18px 28px', display: 'flex', gap: 40, alignItems: 'center' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)' }}>Pipeline heartbeat</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, color: 'var(--sl-navy-ink)', marginTop: 4 }}>{fmtAge(pipelineFreshness)}</div>
            </div>
            {Object.entries(sourceFreshness).map(([k, v]) => (
              <div key={k}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)' }}>{k}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, color: 'var(--sl-navy-ink)', marginTop: 4 }}>{fmtAge(v)}</div>
              </div>
            ))}
          </div>
        )}

        {/* Sources grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 64, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 01</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>DATA SOURCES</div>
          </aside>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
            {SOURCES.map((s, i) => (
              <div key={s.name} style={{ paddingTop: 28, borderTop: i === 0 ? 'none' : '1px solid var(--sl-line-soft)', display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 40 }}>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', color: 'var(--sl-muted)', letterSpacing: '0.1em' }}>{s.org}</div>
                  <div style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy-ink)', fontWeight: 400, marginTop: 6, marginBottom: 8 }}>{s.name}</div>
                  {s.freshness_key && sourceFreshness[s.freshness_key] && (
                    <div style={{ display: 'inline-block', background: 'var(--sl-risk-low-bg)', color: 'var(--sl-risk-low-ink)', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '3px 10px', borderRadius: 20 }}>
                      Last seen {fmtAge(sourceFreshness[s.freshness_key])}
                    </div>
                  )}
                  <div style={{ marginTop: 16, fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', color: 'var(--sl-muted)', letterSpacing: '0.08em' }}>Update cadence</div>
                  <div style={{ fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-ink)', marginTop: 4, lineHeight: 1.5 }}>{s.freq}</div>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-block', marginTop: 16, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-navy)', textDecoration: 'none', borderBottom: '1px solid var(--sl-line)' }}>
                    {s.url.replace('https://', '')} ↗
                  </a>
                </div>
                <div>
                  <p style={{ fontFamily: 'var(--font-text)', fontSize: 15, color: 'var(--sl-ink)', lineHeight: 1.65, margin: '0 0 16px' }}>{s.what}</p>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', color: 'var(--sl-muted)', letterSpacing: '0.08em', marginBottom: 8 }}>Fields used</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {s.fields.map(f => (
                      <span key={f} style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', fontFamily: 'var(--font-mono)', fontSize: 11, padding: '3px 10px', borderRadius: 6, color: 'var(--sl-ink)' }}>{f}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Pipeline note */}
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 64,
          marginTop: 80, paddingTop: 32, borderTop: '1px solid var(--sl-line)' }}>
          <aside>
            <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>§ 02</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.6, letterSpacing: '0.06em' }}>PIPELINE</div>
          </aside>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 36, margin: '0 0 20px', fontWeight: 400, letterSpacing: '-0.01em', color: 'var(--sl-navy-ink)' }}>
              Forecast-safe cutoff at 5 AM PT.
            </h2>
            <p style={{ fontFamily: 'var(--font-text)', fontSize: 16, color: 'var(--sl-ink)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
              The pipeline runs daily at 6 AM PT. All environmental covariates are summarised up to
              5 AM PT of the forecast day so no same-morning laboratory results leak into the
              features. Open-Meteo data is cached per (lat, lon, date) in a local parquet store
              and incrementally updated; a full 6-year backfill runs only on the first cold-cache
              CI run.
            </p>
            <a href="https://github.com/kylechoi101/surf-health/blob/main/CLAUDE.md" target="_blank" rel="noopener noreferrer"
              style={{ display: 'inline-block', marginTop: 20, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sl-navy)', textDecoration: 'none', border: '1px solid var(--sl-line)', padding: '10px 18px', borderRadius: 8, background: 'var(--sl-ecru)' }}>
              Pipeline reference →
            </a>
          </div>
        </div>

      </article>
    </EditorialPage>
  );
}
