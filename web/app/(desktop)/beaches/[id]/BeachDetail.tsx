"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getBeaches, getForecast, getObservations, preferredForecastDate, type BeachSummary, type ForecastRecord, type ObservationResponse } from "@/lib/api";
import { DropRow, SeverityBar, RiskChip } from "@/components/RiskComponents";
import { RISK_COPY, RISK_TOKEN } from "@/lib/riskData";
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
    <span className={`inline-flex items-center ml-1 text-sm transition-transform duration-300 ${isGood ? 'text-emerald-600' : 'text-red-500'} ${isUp ? 'rotate-0' : 'rotate-180'}`}>
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
    <main className="min-h-screen bg-background pt-32 pb-24">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end pb-8 mb-12 border-b border-border/50 gap-6">
          <div>
            <Skeleton style={{ width: 120, height: 14, marginBottom: 8 }} />
            <Skeleton style={{ width: 400, height: 72 }} />
          </div>
          <Skeleton style={{ width: 100, height: 32 }} />
        </div>
        <div className="grid lg:grid-cols-[1.2fr_1fr] gap-12">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    </main>
  );

  if (!beach) return (
    <main className="min-h-screen bg-background pt-32 pb-24 flex items-center justify-center">
      <div className="text-xl text-muted-foreground font-mono">Beach not found.</div>
    </main>
  );

  if (!forecast) {
    const date = preferredForecastDate();
    return (
      <main className="min-h-screen bg-background pt-32 pb-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
            {beach.county} County · {beach.region}
          </div>
          <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
            {beach.name}
          </h1>
          <p className="text-xl text-muted-foreground leading-relaxed max-w-2xl mb-12">
            No forecast is available for {beach.name} on {date}. The model runs each morning — check back after 6 AM PT.
          </p>
          <Link href="/beaches" className="font-mono text-[11px] tracking-widest text-primary border-b border-border/50 hover:border-primary transition-colors pb-0.5">
            ← Back to all beaches
          </Link>
        </div>
      </main>
    );
  }

  const isUnsupported = beach.support_status === 'unsupported';
  const band = forecast.risk_band;
  // Fallback to Tailwind-like styles for unsupported
  const cardBgClass = isUnsupported ? 'bg-muted/30' : RISK_TOKEN[band]?.bgClass || 'bg-muted/30';
  const cardBorderClass = isUnsupported ? 'border-border/50' : RISK_TOKEN[band]?.borderClass || 'border-border/50';
  const cardTextClass = isUnsupported ? 'text-muted-foreground' : RISK_TOKEN[band]?.textClass || 'text-foreground';
  
  const copy = isUnsupported ? { head: "No model coverage", sub: "This beach is not in Shorelife's modeled coverage yet. Use the latest official sample as the primary signal." } : RISK_COPY[band];
  const env = forecast?.environmental_summary;
  
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
    <main className="min-h-screen bg-background pt-32 pb-24">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 animate-fade-in">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end pb-8 mb-12 border-b border-border/50 gap-6">
          <div>
            <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
              {beach.county} County · {beach.region}
            </div>
            <h1 className="text-5xl md:text-7xl font-light m-0 text-foreground text-balance tracking-tight">
              {beach.name}
            </h1>
          </div>
          <div className="text-left md:text-right">
            {!isUnsupported && <RiskChip band={band}/>}
            <div className="mt-3 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              LAT {beach.geometry.latitude.toFixed(3)} · LON {Math.abs(beach.geometry.longitude).toFixed(3)}
            </div>
          </div>
        </div>

        <div className="grid lg:grid-cols-[1.2fr_1fr] gap-12">
          <div>
            {/* Main Risk Card */}
            <div className={`rounded-3xl p-8 md:p-10 border ${cardBgClass} ${cardBorderClass}`}>
              {isUnsupported ? (
                <div className="flex items-center gap-3">
                  <div className={`font-mono text-xs tracking-[0.2em] font-semibold uppercase ${cardTextClass}`}>
                    Official sample only
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <DropRow band={band} size={18}/>
                  <div className={`font-mono text-xs tracking-[0.2em] font-semibold uppercase ${cardTextClass}`}>
                    {band} · Forecast
                  </div>
                </div>
              )}
              <div className={`text-6xl sm:text-7xl md:text-[5.5rem] leading-[0.9] mt-8 mb-6 font-light tracking-tight ${cardTextClass}`}>
                {copy.head}
              </div>
              <p className={`text-lg md:text-xl leading-relaxed max-w-lg opacity-90 ${cardTextClass}`}>
                {copy.sub}
              </p>
              
              <div className={`mt-10 pt-6 border-t border-dashed ${cardBorderClass}`}>
                {isUnsupported ? (
                  <div className={`flex flex-wrap justify-between gap-3 font-mono text-[10px] uppercase tracking-widest opacity-80 ${cardTextClass}`}>
                    <span>Latest official sample</span>
                    <span>{beach.latest_official_sample_at ? new Date(beach.latest_official_sample_at).toLocaleDateString() : 'Unknown'}</span>
                  </div>
                ) : (
                  <>
                    <SeverityBar band={band} width="100%" height={8}/>
                    <div className={`flex justify-between items-center mt-4 font-mono text-[10px] uppercase tracking-widest opacity-80 ${cardTextClass}`}>
                      <span>Exceedance chance: {forecast ? Math.round(forecast.p_exceed * 100) : '--'}%</span>
                      <span>Threshold: 104 CFU</span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Forecast Drivers */}
            {!isUnsupported && forecast && forecast.top_drivers.length > 0 && (
              <div className="mt-16">
                <h2 className="text-2xl font-light text-foreground mb-6">Model drivers</h2>
                <div className="flex flex-col gap-3">
                  {forecast.top_drivers.map((d, i) => (
                    <div key={i} className="px-5 py-4 bg-muted/30 rounded-xl border border-border/50 flex items-center gap-4">
                      <span className="font-mono text-[10px] tracking-widest text-muted-foreground">0{i+1}</span>
                      <span className="text-sm sm:text-base text-foreground">{d}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* History Sparkline / Table */}
            {obs && obs.observations.length > 0 && (
              <div className="mt-16">
                <h2 className="text-2xl font-light text-foreground mb-6">Recent samples</h2>
                <div className="bg-muted/30 border border-border/50 rounded-2xl overflow-hidden">
                  <div className="grid grid-cols-[1fr_120px_100px] px-6 py-4 border-b border-border/50 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    <span>Date</span><span>Value</span><span className="text-center">Result</span>
                  </div>
                  {obs.observations.slice(0, 5).map((o, i, arr) => (
                    <div key={i} className={`grid grid-cols-[1fr_120px_100px] px-6 py-5 items-center ${i === arr.length - 1 ? '' : 'border-b border-border/50'}`}>
                      <span className="text-sm sm:text-base text-foreground">{new Date(o.sample_time).toLocaleDateString()}</span>
                      <span className="font-mono text-sm font-medium text-foreground flex items-center">
                        {o.value} <small className="font-normal text-muted-foreground ml-1">{o.units}</small>
                        {i < obs.observations.length - 1 && (
                          <TrendIndicator current={o.value} previous={obs.observations[i+1].value} reverse={true} />
                        )}
                      </span>
                      <span className={`px-2 py-1 rounded-md text-[10px] font-mono tracking-widest text-center mx-auto ${
                        o.exceeds_stv ? 'bg-red-500/20 text-red-700' : 'bg-emerald-500/10 text-emerald-600'
                      }`}>
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
            <div className="bg-muted/30 border border-border/50 rounded-3xl p-8">
              <h2 className="text-2xl font-light text-foreground mb-8">Ocean context</h2>
              <div className="grid grid-cols-2 gap-4">
                {conditions.map(c => (
                  <div key={c.l} className="p-5 bg-background rounded-2xl border border-border/50">
                    <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2">{c.l}</div>
                    <div className="flex items-baseline">
                      <div className="text-2xl sm:text-3xl font-light text-foreground">{c.v}</div>
                      {c.trend}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Sidebar / Map Context */}
            <div className="mt-8 p-8 bg-muted/30 border border-border/50 rounded-3xl">
              <h2 className="text-xl font-medium text-foreground mb-6">Station Metadata</h2>
              <div className="flex flex-col gap-4 text-sm text-foreground">
                <div className="flex justify-between items-center py-2 border-b border-border/50">
                  <span className="text-muted-foreground">Status</span>
                  <span className="capitalize">{beach.support_status}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-border/50">
                  <span className="text-muted-foreground">Latest Official Sample</span>
                  <span>{beach.latest_official_sample_at ? new Date(beach.latest_official_sample_at).toLocaleDateString() : 'None'}</span>
                </div>
                <div className="flex justify-between items-center py-2">
                  <span className="text-muted-foreground">Region</span>
                  <span>{beach.region}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
