"use client";
import React, { useEffect, useState, useMemo } from "react";
import { CaliforniaPosterMap } from "@/components/CaliforniaPosterMap";
import { ShorelineCrossSection } from "@/components/ShorelineCrossSection";
import { RiskChip, RISK_COPY, RISK_TOKEN, DropRow, SeverityBar } from "@/components/Risk";
import { LockupHorizontal } from "@/components/Lockup";
import { Skeleton, SkeletonCard } from "@/components/Skeleton";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";

export default function HomePage() {
  const [beaches, setBeaches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingFeatured, setLoadingFeatured] = useState(true);
  const [activeBeach, setActiveBeach] = useState<any | null>(null);

  useEffect(() => {
    const date = preferredForecastDate();
    getBeaches().then(async (bs) => {
      const pairs = await Promise.all(
        bs.map(async (b) => {
          try {
            const f = await getForecast(b.id, date);
            return {
              ...b,
              lat: b.geometry?.latitude,
              lon: b.geometry?.longitude,
              risk: f?.risk_band || 'Moderate',
              p: f?.p_exceed || 0,
              waveFt: f?.environmental_summary?.wave_height_m ? (f.environmental_summary.wave_height_m * 3.281).toFixed(1) : '--',
              temp: f?.environmental_summary?.water_temperature_c ? Math.round(f.environmental_summary.water_temperature_c * 9/5 + 32) : '--',
              period: f?.environmental_summary?.dominant_period_s ? Math.round(f.environmental_summary.dominant_period_s) : '--',
            };
          } catch {
            return { ...b, risk: 'Moderate', p: 0, waveFt: '--', temp: '--', period: '--' };
          }
        })
      );
      setBeaches(pairs);
      setActiveBeach(pairs.find(b => b.id === 'ca298722-orange-aliso-county-beach-s8') || pairs[0]);
    }).finally(() => {
      setLoading(false);
      setLoadingFeatured(false);
    });
  }, []);

  const heroBand = activeBeach?.risk || 'Low';
  const copy = RISK_COPY[heroBand] || RISK_COPY['Low'];
  const tok = RISK_TOKEN[heroBand] || RISK_TOKEN['Low'];

  const featuredIds = ['ca009204-san-diego-carlsbad-state-beach-eh-460', 'ca799523-san-diego-ocean-beach-pl-080', 'ca853136-orange-laguna-beach-cleoz'];
  const featured = useMemo(() => beaches.filter(b => featuredIds.includes(b.id)).slice(0, 3), [beaches]);

  return (
    <main className="page-shell animate-fade" style={{ paddingTop: 48 }}>
      {/* HERO SECTION — Academic Layout (0.28 / 0.72 split) */}
      <section style={{ display: 'flex', gap: 48, marginBottom: 80, alignItems: 'flex-start' }}>
        {/* Left Column — 28% width */}
        <div style={{ flex: '0 0 380px' }}>
          <div className="eyebrow">◐ Live forecast · {preferredForecastDate()}</div>
          <h1 style={{ fontSize: 64, lineHeight: 1.0, marginBottom: 24 }}>
            Know before you<br/>paddle out.
          </h1>
          <p style={{ color: 'var(--sl-muted)', fontSize: 16, marginBottom: 32 }}>
            Shorelife transforms official bacterial sampling and coastal physics into a daily predictive risk model for {loading ? '...' : beaches.length}+ California marine stations.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {loading ? <Skeleton style={{ height: 200 }} /> : (
              <div className="panel" style={{ padding: 24, background: tok.bg, borderColor: tok.c }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: tok.ink }}>{heroBand.toUpperCase()}</div>
                  <DropRow band={heroBand} size={14}/>
                </div>
                <div style={{ fontFamily: 'var(--font-heading)', fontSize: 42, color: tok.ink, marginBottom: 12 }}>{copy.head}</div>
                <div style={{ fontSize: 14, color: tok.ink, opacity: 0.8, lineHeight: 1.5, marginBottom: 20 }}>{copy.sub}</div>
                <SeverityBar band={heroBand} width="100%" height={5}/>
                <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px dashed ${tok.c}`, display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--font-mono)', color: tok.ink, opacity: 0.7 }}>
                  <span>EXCEED {Math.round(activeBeach?.p * 100)}%</span>
                  <span>SAMPLED 2D AGO</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column — Map & Visuals */}
        <div style={{ flex: 1 }}>
          <CaliforniaPosterMap
            beaches={beaches}
            activeBeach={activeBeach}
            onSelect={setActiveBeach}
            height={720}/>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 16, fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--sl-muted)' }}>
            <span>Fig 01. Statewide Nearshore Monitoring Network</span>
            <span>290+ Active Stations</span>
          </div>
        </div>
      </section>

      {/* CROSS-SECTION — Academic Illustration */}
      <section style={{ marginBottom: 96 }}>
        <div className="eyebrow">02 · System Model</div>
        <h2 style={{ fontSize: 32, marginBottom: 32 }}>Physical modeling of the surf zone.</h2>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
          <ShorelineCrossSection band={heroBand} height={380}/>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 32, marginTop: 24 }}>
          {[
            { k: 'Offshore', v: 'NDBC buoy swell height, period, direction' },
            { k: 'Mid-shelf', v: 'CDIP nearshore wave model + SST' },
            { k: 'Surf zone', v: 'Culture sample history + exceedance prior' },
            { k: 'Swash', v: 'Tide stage, runoff index, last advisory' },
          ].map(c => (
            <div key={c.k}>
              <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', marginBottom: 6 }}>{c.k}</div>
              <div style={{ fontSize: 13, color: 'var(--sl-muted)', lineHeight: 1.5 }}>{c.v}</div>
            </div>
          ))}
        </div>
      </section>

      {/* FEATURED GRID — Academic Precision */}
      <section style={{ marginBottom: 96 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 40 }}>
          <div>
            <div className="eyebrow">03 · Today's forecast</div>
            <h2 style={{ fontSize: 32 }}>Regional spotlight.</h2>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button>All Counties</button>
            <button style={{ background: 'transparent', color: 'var(--sl-muted)' }}>Favorites</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>
          {loadingFeatured ? [...Array(3)].map((_, i) => <SkeletonCard key={i} />) : (
            featured.map(b => (
              <article key={b.id} className="card" onClick={() => window.location.href = `/beaches/${b.id}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div>
                    <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)', textTransform: 'uppercase', marginBottom: 4 }}>{b.county}</div>
                    <h3 style={{ fontSize: 20 }}>{b.name}</h3>
                  </div>
                  <RiskChip band={b.risk}/>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, padding: '12px 0', borderTop: '1px solid var(--border-soft)', borderBottom: '1px solid var(--border-soft)', marginBottom: 16 }}>
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)' }}>SURF</div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{b.waveFt}ft</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)' }}>TEMP</div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{b.temp}°F</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)' }}>EXCEED</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: RISK_TOKEN[b.risk]?.ink }}>{Math.round(b.p * 100)}%</div>
                  </div>
                </div>
                <SeverityBar band={b.risk} width="100%" height={4}/>
              </article>
            ))
          )}
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{ padding: '80px 0 48px', borderTop: '1px solid var(--sl-line)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 64 }}>
          <div>
            <LockupHorizontal size={24} subtitle="California Water Quality"/>
            <p style={{ fontSize: 14, color: 'var(--sl-muted)', marginTop: 20, maxWidth: 360 }}>
              Independent predictive modeling for marine public health. Shorelife uses machine learning to bridge the gap between weekly official lab samples.
            </p>
          </div>
          {[
            { t: 'Analysis', l: ['Daily Forecast', 'Station Map', 'API Access'] },
            { t: 'Science', l: ['Methodology', 'Validation', 'Data Sources'] },
            { t: 'About', l: ['Project Team', 'Contact', 'Terms'] },
          ].map(c => (
            <div key={c.t}>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 20 }}>{c.t}</div>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {c.l.map(li => <li key={li} style={{ fontSize: 13, color: 'var(--sl-muted)' }}>{li}</li>)}
              </ul>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 64, paddingTop: 24, borderTop: '1px solid var(--sl-line-soft)', display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)', textTransform: 'uppercase', letterSpacing: '0.15em' }}>
          <span>© 2026 Shorelife · v1.4 Deployment</span>
          <span>Scientific Computing · Pacific Coast</span>
        </div>
      </footer>
    </main>
  );
}
