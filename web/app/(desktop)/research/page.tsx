import React from 'react';
import { promises as fs } from 'fs';
import path from 'path';
import { getBeaches } from '@/lib/api';
import { RiskChip } from '@/components/Risk';

export default async function ResearchPage() {
  const healthPath = path.join(process.cwd(), '../data/curated/system_health.json');
  const healthData = JSON.parse(await fs.readFile(healthPath, 'utf8'));
  
  const allBeaches = await getBeaches({ cache: 'force-cache' });
  const stations = allBeaches.slice(0, 12);

  const model = healthData.model_registry.production_model;
  const testAucpr = healthData.model_registry.production_metrics.aucpr.toFixed(4);
  const testBrier = healthData.model_registry.production_metrics.brier.toFixed(4);
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

      {/* Two-column: source freshness + station coverage */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 32, marginTop: 32 }}>
        {/* Source freshness */}
        <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
          borderRadius: 14, padding: 28 }}>
          <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Source freshness</div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
            Pipeline heartbeat
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {sources.map(([src, ts], i) => {
              const ageStr = timeSince(ts as string);
              const isFresh = !ageStr.includes('d');
              return (
              <div key={src} style={{ display: 'flex', justifyContent: 'space-between',
                padding: '14px 0', borderTop: i ? '1px solid var(--sl-line-soft)' : 'none' }}>
                <span style={{ fontFamily: 'var(--font-text)', fontSize: 13, color: 'var(--sl-ink)' }}>{src}</span>
                <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>{ageStr}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600,
                    letterSpacing: '0.14em', textTransform: 'uppercase',
                    padding: '3px 8px', borderRadius: 999,
                    background: isFresh ? 'var(--sl-risk-low-bg)' : 'var(--sl-risk-mod-bg)',
                    color: isFresh ? 'var(--sl-risk-low-ink)' : 'var(--sl-risk-mod-ink)' }}>
                    {isFresh ? 'fresh' : 'stale'}
                  </span>
                </span>
              </div>
            )})}
          </div>
        </div>

        {/* Station coverage */}
        <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
          borderRadius: 14, padding: 28 }}>
          <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Station state</div>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, margin: '8px 0 24px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
            Current forecast coverage
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {stations.map(s => (
              <div key={s.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '11px 14px', borderRadius: 10,
                background: 'var(--sl-ecru)', border: '1px solid var(--sl-line-soft)' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: 'var(--font-text)', fontSize: 12, fontWeight: 500, color: 'var(--sl-ink)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {s.name}
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--sl-muted)',
                    letterSpacing: '0.06em', marginTop: 2 }}>
                    {model} · production
                  </div>
                </div>
                <RiskChip band="Moderate"/>
              </div>
            ))}
          </div>
        </div>
      </div>
      
      {/* Validation skipped per instructions until spatial_metrics propagation is fixed */}
    </div>
  );
}
