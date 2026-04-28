import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import { getBeaches } from '@/lib/api';
import { RiskChip } from '@/components/RiskComponents';
import { EditorialPage } from '@/components/EditorialPage';
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
    <EditorialPage>
    <div style={{ padding: '48px 64px 64px' }}>
      <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Research · operator view · build {new Date().toISOString().split('T')[0].replace(/-/g, '.')}</div>
      <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 80, marginTop: 14, marginBottom: 16, fontWeight: 400, letterSpacing: '-0.02em',
        color: 'var(--sl-navy-ink)' }}>
        Model health &<br/>deployment traceability.
      </h1>
      <p style={{ fontFamily: 'var(--font-text)', fontSize: 17, color: 'var(--sl-ink)', lineHeight: 1.55,
        maxWidth: 720, margin: 0 }}>
        The operator view tracks model registry status, source freshness, and which stations are
        ready for production versus beta fallback.
      </p>

      {/* Registry stats — large mono-numeric strip */}
      <div style={{ marginTop: 56, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 0,
        background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14,
        overflow: 'hidden' }}>
        {[
          ['Production model', model, 'var(--font-heading)', 22],
          ['Test AUCPR', testAucpr, 'var(--font-mono)', 28],
          ['Test Brier', testBrier, 'var(--font-mono)', 28],
          ['Coverage', `${stations.length} / 0`, 'var(--font-mono)', 28, 'production / beta'],
          ['Public release', isEligible, 'var(--font-heading)', 22],
        ].map((r, i) => (
          <div key={i} style={{ padding: '24px 24px',
            borderRight: i < 4 ? '1px solid var(--sl-line-soft)' : 'none' }}>
            <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>{r[0]}</div>
            <div style={{ fontFamily: r[2] as string, fontSize: r[3] as number, color: 'var(--sl-navy-ink)', marginTop: 12 }}>{r[1]}</div>
            {r[4] && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--sl-muted)', marginTop: 4 }}>{r[4]}</div>}
          </div>
        ))}
      </div>

      {/* Validation / Spatial Metrics */}
      {healthData.model_registry.spatial_metrics && (
        <div style={{ marginTop: 32, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, padding: 28 }}>
          <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Spatial backtests</div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
            Performance on unobserved counties
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
            {Object.entries(healthData.model_registry.spatial_metrics).map(([name, m]: [string, any]) => (
              <div key={name} style={{ padding: 18, background: 'var(--sl-ecru)', border: '1px solid var(--sl-line-soft)', borderRadius: 12 }}>
                <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>{name.replace(/_/g, ' ')}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12 }}>
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--sl-muted)', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>AUCPR</div>
                    <div style={{ fontSize: 20, fontFamily: 'var(--font-mono)', color: 'var(--sl-navy-ink)' }}>{m.aucpr.toFixed(3)}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 9, color: 'var(--sl-muted)', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>Brier</div>
                    <div style={{ fontSize: 20, fontFamily: 'var(--font-mono)', color: 'var(--sl-navy-ink)' }}>{m.brier.toFixed(3)}</div>
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 10, color: 'var(--sl-muted)', fontFamily: 'var(--font-text)' }}>
                  {m.folds} folds · {m.heldout_rows} samples
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scientific Artifacts */}
      {/* Research subpages */}
      <div style={{ marginTop: 32 }}>
        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Deep dives</div>
        <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
          Transparency documentation
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
          {[
            { href: '/research/labels', title: 'Risk Labels', desc: 'How exceedance probability maps to the four public bands, legal basis, and what the model can and cannot predict.', tag: 'Labels · Thresholds' },
            { href: '/research/sources', title: 'Data Sources', desc: 'The six primary datasets feeding the pipeline — BeachWatch, NDBC, CDIP, Open-Meteo, USGS NWIS, and CEDEN — with freshness status.', tag: 'Provenance · Cadence' },
            { href: '/research/calibration', title: 'Calibration', desc: 'Live production metrics, spatial backtest results, and candidate model registry from the latest CI run.', tag: 'AUCPR · Brier · Spatial CV' },
          ].map(({ href, title, desc, tag }) => (
            <div key={href} style={{ padding: 24, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: 20 }}>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)', marginBottom: 8 }}>{tag}</div>
                <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 22, margin: '0 0 8px', color: 'var(--sl-navy)', fontWeight: 400 }}>{title}</h3>
                <p style={{ fontSize: 13, color: 'var(--sl-muted)', margin: 0, lineHeight: 1.55 }}>{desc}</p>
              </div>
              <Link href={href} style={{
                padding: '9px 16px', borderRadius: 8, border: '1px solid var(--sl-line)',
                background: 'var(--sl-ecru)', color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)',
                fontSize: 11, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap',
                alignSelf: 'flex-start',
              }}>READ →</Link>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 32, padding: '0 0 64px' }}>
        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Scientific artifacts</div>
        <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
          Open data & methodology
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <div style={{ padding: 24, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 20, margin: '0 0 6px', color: 'var(--sl-navy)' }}>Technical Methodology</h3>
              <p style={{ fontSize: 13, color: 'var(--sl-muted)', margin: '0 0 12px', maxWidth: 360, lineHeight: 1.5 }}>
                Model design, risk-band calibration, spatial holdout protocol, and known limitations.
              </p>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--sl-muted)' }}>
                Shorelife Team
              </div>
            </div>
            <Link href="/methodology" style={{
              padding: '10px 18px', borderRadius: 8, border: '1px solid var(--sl-line)',
              background: 'var(--sl-ecru)', color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)',
              fontSize: 11, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap',
            }}>READ →</Link>
          </div>
          <div style={{ padding: 24, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 20, margin: '0 0 6px', color: 'var(--sl-navy)' }}>Source Code & Data</h3>
              <p style={{ fontSize: 13, color: 'var(--sl-muted)', margin: '0 0 12px', maxWidth: 360, lineHeight: 1.5 }}>
                Full pipeline, training scripts, and curated datasets available on GitHub under an open-source license.
              </p>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--sl-muted)' }}>
                Automated Pipeline
              </div>
            </div>
            <a href="https://github.com/kylechoi101/surf-health" target="_blank" rel="noopener noreferrer" style={{
              padding: '10px 18px', borderRadius: 8, border: '1px solid var(--sl-line)',
              background: 'var(--sl-ecru)', color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)',
              fontSize: 11, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap',
            }}>GITHUB →</a>
          </div>
        </div>
      </div>
    </div>
    </EditorialPage>
  );
}
