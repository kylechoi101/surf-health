"use client";
import React, { useEffect, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { getBeaches, getForecast, getObservations, preferredForecastDate, type BeachSummary, type ForecastRecord, type ObservationResponse } from "@/lib/api";
import { RISK_COPY, RISK_TOKEN, DropRow, SeverityBar, RiskChip } from "@/components/RiskComponents";
import { Skeleton, SkeletonCard } from "@/components/Skeleton";

function mToFt(m: number | null | undefined) {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

function TrendIndicator({ current, previous, reverse = false }: { current: number | null | undefined, previous: number | null | undefined, reverse?: boolean }) {
  if (current == null || previous == null || current === previous) return null;
  const isUp = current > previous;
  const isGood = reverse ? !isUp : isUp;
  return (
    <span style={{ 
      display: 'inline-flex', 
      alignItems: 'center', 
      marginLeft: 4, 
      color: isGood ? 'var(--sl-teal-deep)' : 'var(--sl-risk-high)',
      fontSize: 14,
      transform: isUp ? 'rotate(0deg)' : 'rotate(180deg)',
      transition: 'transform 0.3s ease'
    }}>
      ↑
    </span>
  );
}

export default function BeachDetailPage() {
  const { id } = useParams();
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [obs, setObs] = useState<ObservationResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const bid = Array.isArray(id) ? id[0] : id;
    const date = preferredForecastDate();

    Promise.all([
      getBeaches().then(bs => bs.find(b => b.id === bid) || null),
      getForecast(bid, date).catch(() => null),
      getObservations(bid).catch(() => null),
    ]).then(([b, f, o]) => {
      setBeach(b);
      setForecast(f);
      setObs(o);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) return (
    <div style={{ padding: '48px 64px 64px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', paddingBottom: 32, borderBottom: '1px solid var(--sl-line)' }}>
        <div>
          <Skeleton style={{ width: 120, height: 14, marginBottom: 8 }} />
          <Skeleton style={{ width: 400, height: 72 }} />
        </div>
        <Skeleton style={{ width: 100, height: 32 }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 48, marginTop: 48 }}>
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );

  if (!beach) return <div style={{ padding: 64 }}>Beach not found.</div>;

  if (!forecast) {
    const date = preferredForecastDate();
    return (
      <div style={{ padding: '48px 64px 64px' }}>
        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
          {beach.county} County · {beach.region}
        </div>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 72, margin: '0 0 24px', fontWeight: 400, color: 'var(--sl-navy-ink)', letterSpacing: '-0.02em' }}>
          {beach.name}
        </h1>
        <p style={{ fontFamily: 'var(--font-text)', fontSize: 17, color: 'var(--sl-muted)', lineHeight: 1.55, marginBottom: 32, maxWidth: 560 }}>
          No forecast is available for {beach.name} on {date}. The model runs each morning — check back after 6 AM PT.
        </p>
        <a href="/beaches" style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--sl-navy)', textDecoration: 'none' }}>
          ← Back to all beaches
        </a>
      </div>
    );
  }

  const band = forecast.risk_band;
  const tok = RISK_TOKEN[band];
  const copy = RISK_COPY[band];
  const env = forecast?.environmental_summary;
  
  // Basic trend comparison if history exists
  const prevEnv = obs?.recent_environment && obs.recent_environment.length > 1 ? obs.recent_environment[1] : null;

  const conditions = [
    { 
      l: 'Wave Height', 
      v: mToFt(env?.wave_height_m),
      trend: <TrendIndicator current={env?.wave_height_m} previous={Number(prevEnv?.wave_height_m)} />
    },
    { 
      l: 'Period', 
      v: env?.dominant_period_s ? `${Math.round(env.dominant_period_s)}s` : '—',
      trend: <TrendIndicator current={env?.dominant_period_s} previous={Number(prevEnv?.dominant_period_s)} />
    },
    { 
      l: 'Water Temp', 
      v: env?.water_temperature_c ? `${Math.round(env.water_temperature_c * 9/5 + 32)}°F` : '—',
      trend: <TrendIndicator current={env?.water_temperature_c} previous={Number(prevEnv?.water_temperature_c)} />
    },
    { 
      l: 'UV Index', 
      v: env?.uv_index ? Math.round(env.uv_index) : '—',
      trend: <TrendIndicator current={env?.uv_index} previous={Number(prevEnv?.uv_index)} reverse={true} />
    },
    { 
      l: 'Wind Speed', 
      v: env?.wind_speed_mps ? `${Math.round(env.wind_speed_mps * 2.237)} mph` : '—',
      trend: <TrendIndicator current={env?.wind_speed_mps} previous={Number(prevEnv?.wind_speed_mps)} reverse={true} />
    },
    { 
      l: 'Salinity', 
      v: env?.salinity_psu ? `${env.salinity_psu.toFixed(1)} psu` : '—',
      trend: <TrendIndicator current={env?.salinity_psu} previous={Number(prevEnv?.salinity_psu)} />
    },
  ];

  return (
    <div style={{ padding: '48px 64px 64px' }} className="animate-fade">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', paddingBottom: 32, borderBottom: '1px solid var(--sl-line)' }}>
        <div>
          <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>{beach.county} County · {beach.region}</div>
          <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 72, margin: 0, fontWeight: 400, color: 'var(--sl-navy-ink)', letterSpacing: '-0.02em' }}>{beach.name}</h1>
        </div>
        <div style={{ textAlign: 'right' }}>
          <RiskChip band={band}/>
          <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>LAT {beach.geometry.latitude.toFixed(3)} · LON {Math.abs(beach.geometry.longitude).toFixed(3)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 48, marginTop: 48 }}>
        <div>
          {/* Main Risk Card */}
          <div style={{ background: tok.bg, border: `1px solid ${tok.c}`, borderRadius: 18, padding: '40px', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <DropRow band={band} size={18}/>
              <div style={{ color: tok.ink, fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.14em', fontWeight: 600 }}>{band.toUpperCase()} · FORECAST</div>
            </div>
            <div style={{ fontSize: 96, lineHeight: 0.9, color: tok.ink, marginTop: 24, marginBottom: 16, fontFamily: 'var(--font-heading)', fontWeight: 400 }}>{copy.head}</div>
            <p style={{ fontSize: 18, color: tok.ink, opacity: 0.85, lineHeight: 1.5, margin: 0, fontFamily: 'var(--font-text)', maxWidth: 480 }}>{copy.sub}</p>
            
            <div style={{ marginTop: 40, paddingTop: 24, borderTop: `1px dashed ${tok.c}` }}>
              <SeverityBar band={band} width="100%" height={8}/>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontFamily: 'var(--font-mono)', fontSize: 11, color: tok.ink, opacity: 0.7 }}>
                <span>Exceedance chance: {forecast ? Math.round(forecast.p_exceed * 100) : '--'}%</span>
                <span>Threshold: 104 CFU/100mL</span>
              </div>
            </div>
          </div>

          {/* Forecast Drivers */}
          {forecast && forecast.top_drivers.length > 0 && (
            <div style={{ marginTop: 48 }}>
              <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', fontWeight: 400, marginBottom: 20 }}>Model drivers</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {forecast.top_drivers.map((d, i) => (
                  <div key={i} style={{ padding: '16px 20px', background: 'var(--sl-bone)', borderRadius: 12, border: '1px solid var(--sl-line)', display: 'flex', gap: 16 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)' }}>0{i+1}</span>
                    <span style={{ fontSize: 15, color: 'var(--sl-ink)', fontFamily: 'var(--font-text)' }}>{d}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* History Sparkline / Table */}
          {obs && obs.observations.length > 0 && (
            <div style={{ marginTop: 48 }}>
              <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', fontWeight: 400, marginBottom: 20 }}>Recent samples</h2>
              <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 12, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px 100px', padding: '12px 20px', borderBottom: '1px solid var(--sl-line)', fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
                  <span>Date</span><span>Value</span><span>Result</span>
                </div>
                {obs.observations.slice(0, 5).map((o, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 120px 100px', padding: '16px 20px', borderBottom: i === 4 ? 'none' : '1px solid var(--sl-line-soft)', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'var(--font-text)', fontSize: 14 }}>{new Date(o.sample_time).toLocaleDateString()}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 500 }}>
                      {o.value} <small style={{ fontWeight: 400, color: 'var(--sl-muted)' }}>{o.units}</small>
                      {i < obs.observations.length - 1 && (
                        <TrendIndicator current={o.value} previous={obs.observations[i+1].value} reverse={true} />
                      )}
                    </span>
                    <span style={{ 
                      color: o.exceeds_stv ? 'var(--sl-risk-high-ink)' : 'var(--sl-risk-low-ink)',
                      background: o.exceeds_stv ? 'var(--sl-risk-high-bg)' : 'var(--sl-risk-low-bg)',
                      padding: '4px 8px', borderRadius: 6, fontSize: 10, fontFamily: 'var(--font-mono)', textAlign: 'center', width: 'fit-content'
                    }}>
                      {o.exceeds_stv ? 'EXCEED' : 'CLEAN'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div>
          {/* Conditions Grid */}
          <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 18, padding: 32 }}>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', fontWeight: 400, marginBottom: 24 }}>Ocean context</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {conditions.map(c => (
                <div key={c.l} style={{ padding: '16px 20px', background: 'var(--sl-ecru)', borderRadius: 12, border: '1px solid var(--sl-line-soft)' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', color: 'var(--sl-muted)', letterSpacing: '0.05em' }}>{c.l}</div>
                  <div style={{ display: 'flex', alignItems: 'baseline' }}>
                    <div style={{ fontFamily: 'var(--font-heading)', fontSize: 24, color: 'var(--sl-navy-ink)', marginTop: 8 }}>{c.v}</div>
                    {c.trend}
                  </div>
                </div>
              ))}
            </div>
          </div>


          {/* Sidebar / Map Context */}
          <div style={{ marginTop: 32, padding: 32, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 18 }}>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 24, color: 'var(--sl-navy)', fontWeight: 400, marginBottom: 16 }}>Station Metadata</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontFamily: 'var(--font-text)', fontSize: 14, color: 'var(--sl-ink)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--sl-muted)' }}>Status</span>
                <span style={{ textTransform: 'capitalize' }}>{beach.support_status}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--sl-muted)' }}>Latest Official Sample</span>
                <span>{beach.latest_official_sample_at ? new Date(beach.latest_official_sample_at).toLocaleDateString() : 'None'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--sl-muted)' }}>Region</span>
                <span>{beach.region}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
