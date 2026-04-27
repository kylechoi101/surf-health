"use client";
import React, { useEffect, useState, useMemo } from "react";
import { CaliforniaPosterMap } from "@/components/CaliforniaPosterMap";
import { ShorelineCrossSection } from "@/components/ShorelineCrossSection";
import { RiskChip, RISK_COPY, RISK_TOKEN, DropRow, SeverityBar } from "@/components/Risk";
import { LockupHorizontal } from "@/components/Lockup";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";

export default function HomePage() {
  const [beaches, setBeaches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
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
              waveFt: f?.environmental_summary?.wave_height_m ? (f.environmental_summary.wave_height_m * 3.28).toFixed(1) : '--',
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
    }).finally(() => setLoading(false));
  }, []);

  const heroBand = activeBeach?.risk || 'Low';
  const copy = RISK_COPY[heroBand] || RISK_COPY['Low'];
  const tok = RISK_TOKEN[heroBand] || RISK_TOKEN['Low'];

  const featuredIds = ['ca009204-san-diego-carlsbad-state-beach-eh-460', 'ca799523-san-diego-ocean-beach-pl-080', 'ca853136-orange-laguna-beach-cleoz'];
  const featured = useMemo(() => beaches.filter(b => featuredIds.includes(b.id)).slice(0, 3), [beaches]);

  return (
    <main className="page-shell" style={{ position: 'relative', zIndex: 1, paddingBottom: 0 }}>
      {/* HERO */}
      <section style={{ padding: '48px 64px 32px', display: 'grid',
        gridTemplateColumns: '1fr 580px', gap: 48, alignItems: 'start' }}>
        <div>
          <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
            ◐ Live forecast · {preferredForecastDate()}
          </div>
          <h1 style={{
            fontFamily: 'var(--font-heading)', fontSize: 92, marginTop: 18, marginBottom: 0, fontWeight: 400, letterSpacing: '-0.02em',
            color: 'var(--sl-navy-ink)', maxWidth: 720, lineHeight: 0.95
          }}>
            Know before you<br/>paddle out.
          </h1>
          <p style={{ fontSize: 18, color: 'var(--sl-ink)', lineHeight: 1.55,
            maxWidth: 540, marginTop: 24, fontFamily: 'var(--font-text)' }}>
            Shorelife turns sparse official bacteria samples plus ocean and weather context into a
            daily health-risk forecast for <span style={{ color: 'var(--sl-navy)', fontWeight: 600 }}>
            {loading ? '...' : beaches.length}+ California marine beaches</span>.
          </p>

          <div style={{ marginTop: 36, display: 'inline-flex', alignItems: 'stretch',
            background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
            borderRadius: 14, overflow: 'hidden',
            boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 8px 24px rgba(11,66,102,0.06)',
          }}>
            <div style={{ background: tok.bg, padding: '20px 24px',
              display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
              minWidth: 200, borderRight: `1px solid var(--sl-line)` }}>
              <div style={{ color: tok.ink, fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', fontWeight: 600 }}>{heroBand.toUpperCase()}</div>
              <div style={{
                fontFamily: 'var(--font-heading)', fontSize: 56, color: tok.ink, lineHeight: 0.9, marginTop: 18, letterSpacing: '-0.02em'
              }}>{copy.head}</div>
              <DropRow band={heroBand} size={14}/>
            </div>
            <div style={{ padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 280 }}>
              <div>
                <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', fontWeight: 600 }}>Today at {activeBeach?.name || '...'}</div>
                <div style={{ fontSize: 14, color: 'var(--sl-ink)', marginTop: 6, lineHeight: 1.5, maxWidth: 280, fontFamily: 'var(--font-text)' }}>
                  {copy.sub}
                </div>
              </div>
              <SeverityBar band={heroBand} width="100%"/>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)',
                paddingTop: 10, borderTop: '1px dashed var(--sl-line)' }}>
                <span>ENT · {copy.cfu}</span>
                <span>SAMPLED · 2d ago</span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 48, marginTop: 36 }}>
            {[
              { k: loading ? '--' : beaches.length, l: 'monitored stations' },
              { k: '5:00a PT', l: 'daily publish' },
              { k: '4', l: 'risk bands' },
            ].map(s => (
              <div key={s.l}>
                <div style={{ fontFamily: 'var(--font-heading)', fontSize: 36, color: 'var(--sl-navy)' }}>{s.k}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', marginTop: 4, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{s.l}</div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <CaliforniaPosterMap
            band={heroBand}
            beaches={beaches}
            activeBeach={activeBeach}
            onSelect={setActiveBeach}
            height={680}/>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12,
            fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
            <span>Fig. 01 · Statewide nearshore health board</span>
            <span>Hover stations →</span>
          </div>
        </div>
      </section>

      {/* CROSS-SECTION INTERLUDE */}
      <section style={{ padding: '32px 64px 0' }}>
        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>02 · How we read the shoreline</div>
        <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 48, marginTop: 12, marginBottom: 24, fontWeight: 400, letterSpacing: '-0.02em',
          color: 'var(--sl-navy-ink)', maxWidth: 720 }}>
          A model of the surf zone, not just a number.
        </h2>
        <div style={{ borderRadius: 14, overflow: 'hidden', border: '1px solid var(--sl-line)',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset' }}>
          <ShorelineCrossSection band={heroBand} height={340}/>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 18, marginTop: 22 }}>
          {[
            { k: 'A · Offshore',   v: 'NDBC buoy swell height, period, direction' },
            { k: 'B · Mid-shelf',  v: 'CDIP nearshore wave model + SST' },
            { k: 'C · Surf zone',  v: 'culture sample history + exceedance prior' },
            { k: 'D · Swash',      v: 'tide stage, runoff index, last advisory' },
          ].map(c => (
            <div key={c.k} style={{ paddingTop: 12, borderTop: '1px solid var(--sl-line)' }}>
              <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', fontWeight: 600, textTransform: 'uppercase' }}>{c.k}</div>
              <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 6, lineHeight: 1.5, fontFamily: 'var(--font-text)' }}>{c.v}</div>
            </div>
          ))}
        </div>
      </section>

      {/* WHY THIS MATTERS — three audience cards */}
      <section style={{ padding: '64px 64px 0' }}>
        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>03 · Who it's for</div>
        <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 48, marginTop: 12, marginBottom: 36, fontWeight: 400, letterSpacing: '-0.02em',
          color: 'var(--sl-navy-ink)' }}>
          Health risk is the missing beach signal.
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
          {[
            { who: 'For surfers', body: 'Check a beach card that combines surf context and water-health risk before you paddle out with a cut, a weak immune system, or after rain.', icon: '◐' },
            { who: 'For agencies', body: 'Use same-day probability estimates to prioritize field visits, spot persistent hot spots, and communicate uncertainty instead of waiting on the next lab run.', icon: '◑' },
            { who: 'For researchers', body: 'Compare official enterococcus labels against nearshore covariates, blocked backtests, and calibrated exceedance forecasts from strong baselines.', icon: '◒' },
          ].map(c => (
            <article key={c.who} style={{
              background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 14, padding: 28,
            }}>
              <div style={{ fontSize: 28, color: 'var(--sl-sun-deep)', lineHeight: 1 }}>{c.icon}</div>
              <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 24, marginTop: 18, marginBottom: 10, fontWeight: 400,
                color: 'var(--sl-navy)' }}>{c.who}</h3>
              <p style={{ fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.6, margin: 0, fontFamily: 'var(--font-text)' }}>{c.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* TODAY'S FORECAST — spotlight grid */}
      <section style={{ padding: '64px 64px 0' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 28 }}>
          <div>
            <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>04 · Today's forecast</div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 48, marginTop: 12, fontWeight: 400, letterSpacing: '-0.02em',
              color: 'var(--sl-navy-ink)' }}>
              What's in the water right now.
            </h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <select style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em',
              padding: '8px 14px', borderRadius: 999, border: '1px solid var(--sl-line)',
              background: 'var(--sl-bone)', color: 'var(--sl-ink)', textTransform: 'uppercase', outline: 'none'
            }}>
              <option>All counties</option><option>Los Angeles</option><option>Orange</option>
            </select>
            <button style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em',
              padding: '8px 14px', borderRadius: 999, border: '1px solid var(--sl-line)',
              background: 'transparent', color: 'var(--sl-muted)', textTransform: 'uppercase', cursor: 'pointer',
            }}>★ Favorites</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
          {featured.map(b => {
            const tok2 = RISK_TOKEN[b.risk];
            return (
              <article key={b.id} style={{
                background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', cursor: 'pointer',
                borderRadius: 14, padding: 22, display: 'flex', flexDirection: 'column', gap: 12,
              }} onClick={() => window.location.href = `/b?id=${b.id}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{b.county}</div>
                    <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 22, margin: '6px 0 0', color: 'var(--sl-navy)', fontWeight: 400 }}>{b.name}</h3>
                  </div>
                  <RiskChip band={b.risk}/>
                </div>
                <div style={{ paddingTop: 10, borderTop: '1px dashed var(--sl-line)',
                  display: 'flex', justifyContent: 'space-between',
                  fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>
                  <span>{b.waveFt}ft @ {b.period}s</span>
                  <span>{b.temp}°F</span>
                  <span style={{ color: tok2?.ink }}>{Math.round(b.p * 100)}% exceed</span>
                </div>
                <SeverityBar band={b.risk} width="100%" height={4}/>
              </article>
            );
          })}
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{ padding: '80px 64px 48px', marginTop: 64, borderTop: '1px solid var(--sl-line)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 48 }}>
          <div>
            <LockupHorizontal size={24} subtitle="California Water Quality"/>
            <p style={{ fontSize: 13, color: 'var(--sl-muted)', lineHeight: 1.6, marginTop: 18, maxWidth: 380, fontFamily: 'var(--font-text)' }}>
              Daily marine-water health forecasts for California beaches. A model forecast — not an official lab result.
              Treat advisories as advisory.
            </p>
          </div>
          {[
            { t: 'Product', l: ['Forecast', 'Beach explorer', 'iOS app', 'Share links'] },
            { t: 'Science', l: ['Methodology', 'Research', 'Sources', 'Caveats'] },
            { t: 'About', l: ['Mission', 'Team', 'Contact', 'Press kit'] },
          ].map(c => (
            <div key={c.t}>
              <div style={{ color: 'var(--sl-navy)', fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>{c.t}</div>
              <ul style={{ listStyle: 'none', padding: 0, margin: '14px 0 0',
                display: 'flex', flexDirection: 'column', gap: 8 }}>
                {c.l.map(li => <li key={li} style={{ fontSize: 13, color: 'var(--sl-muted)', fontFamily: 'var(--font-text)' }}>{li}</li>)}
              </ul>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 48, paddingTop: 24, borderTop: '1px solid var(--sl-line)',
          display: 'flex', justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.16em',
          textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
          <span>© 2026 Shorelife · v1.0</span>
          <span>Made on the Pacific coast</span>
        </div>
      </footer>
    </main>
  );
}