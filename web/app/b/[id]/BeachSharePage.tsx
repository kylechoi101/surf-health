"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";
import { findModeledBeach } from "@/lib/coverage";
import { DropRow, SeverityBar } from "@/components/RiskComponents";
import { RISK_COPY, RISK_TOKEN } from "@/lib/riskData";
import { advisoryProbabilityPresentation, forecastDisplayCopy } from "@/lib/forecastPresentation";
import { formatPacificDate } from "@/lib/utils";

function mToFt(m: number | null | undefined) {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

type ConditionCard = {
  l: string;
  v: string;
  s: string;
};

type BeachSharePageProps = {
  beachId?: string;
};

export default function BeachSharePage({ beachId }: BeachSharePageProps) {
  const params = useParams<{ id?: string | string[] }>();
  const paramId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const resolvedBeachId = beachId ?? paramId ?? null;
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setNotFound(false);

    const date = preferredForecastDate();
    async function load() {
      try {
        const beaches = await getBeaches();
        const selectedBeach = findModeledBeach(beaches, resolvedBeachId);

        if (!selectedBeach) {
          if (!active) return;
          setBeach(null);
          setForecast(null);
          setNotFound(true);
          return;
        }

        const nextForecast = await getForecast(selectedBeach.id, date).catch(() => null);

        if (!active) return;
        setBeach(selectedBeach);
        setForecast(nextForecast);
        setNotFound(false);
      } catch {
        if (!active) return;
        setBeach(null);
        setForecast(null);
        setNotFound(true);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [resolvedBeachId]);

  if (loading) return (
    <main className="min-h-screen bg-background flex items-center justify-center">
      <div className="text-muted-foreground animate-pulse font-mono text-sm tracking-widest uppercase">Loading…</div>
    </main>
  );

  if (notFound || !beach) return (
    <main className="min-h-screen bg-background flex flex-col items-center justify-center gap-6">
      <p className="text-xl text-muted-foreground">Beach not found.</p>
      <Link href="/" className="font-mono text-xs tracking-widest text-primary border-b border-border/50 hover:border-primary transition-colors pb-0.5">← Go to Shorelife</Link>
    </main>
  );

  const band = forecast?.official_advisory_active ? "Very High" : (forecast?.risk_band ?? "Moderate");
  const tok = RISK_TOKEN[band] ?? RISK_TOKEN.Moderate;
  const riskCopy = RISK_COPY[band] ?? RISK_COPY.Moderate;
  const displayCopy = forecastDisplayCopy(forecast, band);
  const probability = advisoryProbabilityPresentation(forecast);
  const signalText = probability.secondaryLabel
    ? forecast?.official_advisory_active
      ? "Official advisory"
      : "Advisory-adjusted display"
    : riskCopy.cfu;
  const env = forecast?.environmental_summary;
  const cardBgClass = tok.bgClass;
  const cardBorderClass = tok.borderClass;
  const cardTextClass = tok.textClass;
  const shareTitle = `${beach.name} · ${displayCopy.headline}`;
  const shareImageSlug = band.toLowerCase().replace(/\s+/g, "-");

  const conditions: ConditionCard[] = [
    { l: 'Surf',  v: mToFt(env?.wave_height_m), s: env?.dominant_period_s ? `@ ${Math.round(env.dominant_period_s)}s` : '—' },
    { l: 'Water', v: env?.water_temperature_c != null ? `${Math.round(env.water_temperature_c * 9/5 + 32)}°F` : '—', s: 'mild' },
    { l: 'Wind',  v: env?.wind_speed_mps != null ? `${Math.round(env.wind_speed_mps * 2.237)} mph` : '—', s: 'WSW' },
    { l: 'UV',    v: env?.uv_index != null ? String(Math.round(env.uv_index)) : '—', s: (env?.uv_index ?? 0) >= 7 ? 'high' : 'moderate' },
  ];

  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="pb-12 border-b border-border/50 mb-12">
          <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">Beach · share preview</div>
          <h1 className="text-5xl md:text-7xl font-light mb-6 text-foreground tracking-tight">
            {beach.name}
          </h1>
          <div className="flex flex-wrap gap-x-6 gap-y-2 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
            <span>{beach.county} County</span>
            <span className="hidden sm:inline">·</span>
            <span>{beach.region ?? 'CA'}</span>
            <span className="hidden sm:inline">·</span>
            <span>{beach.geometry?.latitude?.toFixed(3)}°N · {Math.abs(beach.geometry?.longitude || 0).toFixed(3)}°W</span>
          </div>
        </div>

        <div className="grid lg:grid-cols-[1.2fr_1fr] gap-12 items-start">
          {/* LEFT — full beach detail */}
          <div className="flex flex-col gap-12">
            {/* Big risk hero card */}
            <div className={`rounded-3xl p-8 md:p-12 border ${cardBgClass} ${cardBorderClass} relative overflow-hidden`}>
              {/* Tide-line texture */}
              <svg className="absolute inset-0 w-full h-full opacity-10" viewBox="0 0 600 320" preserveAspectRatio="none">
                {[60, 90, 130, 180, 240].map((y, i) => (
                  <path key={i} d={`M 0 ${y} C 150 ${y - 6}, 300 ${y + 8}, 450 ${y - 4} S 600 ${y}, 600 ${y}`}
                    stroke="currentColor" strokeWidth="1" fill="none" opacity={1 - i*0.15}/>
                ))}
              </svg>
              <div className="relative z-10">
                <div className="flex items-center gap-3 mb-6">
                  <DropRow band={band} size={18}/>
                  <div className={`font-mono text-xs tracking-[0.2em] font-semibold uppercase ${cardTextClass}`}>{band} · {displayCopy.eyebrow}</div>
                </div>
                <div className={`text-6xl sm:text-7xl md:text-[5.5rem] leading-[0.9] font-light tracking-tight mb-6 ${cardTextClass}`}>
                  {displayCopy.headline}
                </div>
                <div className={`text-lg md:text-xl font-mono leading-relaxed max-w-lg opacity-90 ${cardTextClass}`}>
                  {displayCopy.body}
                </div>
                
                <div className={`mt-10 pt-8 border-t border-dashed flex flex-wrap justify-between gap-6 ${cardBorderClass}`}>
                  <div>
                    <div className={`font-mono text-[10px] tracking-widest uppercase font-semibold opacity-70 mb-2 ${cardTextClass}`}>Signal</div>
                    <div className={`text-xl font-mono ${cardTextClass}`}>{signalText}</div>
                  </div>
                  <div className="text-center">
                    <div className={`font-mono text-[10px] tracking-widest uppercase font-semibold opacity-70 mb-2 ${cardTextClass}`}>
                      {probability.primaryLabel}
                    </div>
                    <div className={`text-4xl font-light leading-none ${cardTextClass}`}>
                      {probability.primaryPercent ?? '--'}<span className="text-xl">%</span>
                    </div>
                    {probability.secondaryLabel && (
                      <div className={`mt-2 font-mono text-[10px] uppercase tracking-widest opacity-80 ${cardTextClass}`}>
                        {probability.secondaryLabel}: {probability.secondaryPercent ?? '--'}%
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <div className={`font-mono text-[10px] tracking-widest uppercase font-semibold opacity-70 mb-2 ${cardTextClass}`}>Latest sample</div>
                    <div className={`text-xl font-mono ${cardTextClass}`}>
                      {beach.latest_official_sample_at ? new Date(beach.latest_official_sample_at).toLocaleDateString() : "Unknown"}
                    </div>
                  </div>
                </div>
                <div className="mt-8"><SeverityBar band={band} width="100%" height={6}/></div>
              </div>
            </div>

            {/* Conditions strip */}
            <div>
              <div className="text-primary text-sm tracking-widest uppercase font-medium mb-6">Conditions now</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {conditions.map(c => (
                  <div key={c.l} className="bg-muted/30 border border-border/50 rounded-2xl p-6">
                    <div className="font-mono text-[10px] tracking-widest uppercase text-muted-foreground font-semibold mb-3">{c.l}</div>
                    <div className="text-3xl font-light text-foreground mb-1">{c.v}</div>
                    <div className="font-mono text-[10px] tracking-widest text-muted-foreground">{c.s}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Drivers */}
            {forecast && forecast.top_drivers.length > 0 && (
              <div>
                <div className="text-primary text-sm tracking-widest uppercase font-medium mb-6">What's driving this</div>
                <div className="bg-muted/30 border border-border/50 rounded-2xl overflow-hidden">
                  {forecast.top_drivers.map((d, i) => (
                    <div key={i} className={`p-5 flex items-center gap-5 ${i > 0 ? 'border-t border-border/50' : ''}`}>
                      <span className={`w-8 h-8 rounded-lg ${tok.bgClass} ${tok.textClass} flex items-center justify-center font-mono text-[10px] font-semibold shrink-0`}>
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <p className="m-0 text-sm md:text-base text-foreground font-mono leading-relaxed">{d}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* RIGHT — phone preview + share metadata */}
          <div className="flex flex-col gap-12">
            <div>
              <div className="text-primary text-sm tracking-widest uppercase font-medium mb-6">iOS share preview</div>
              <div className="bg-muted/30 border border-border/50 rounded-3xl p-8 lg:p-12 flex justify-center">
                <PhoneMock
                  beach={beach}
                  band={band}
                  displayCopy={displayCopy}
                  signalText={signalText}
                  p={probability.secondaryPercent ?? probability.primaryPercent ?? 0}
                  pLabel={probability.secondaryLabel ? "MODEL-ONLY" : probability.primaryLabel.toUpperCase()}
                  conditions={conditions}
                />
              </div>
            </div>

            <div>
              <div className="text-primary text-sm tracking-widest uppercase font-medium mb-6">Share link metadata</div>
              <div className="bg-muted/30 border border-border/50 rounded-2xl p-6 font-mono text-[11px] md:text-xs leading-relaxed text-foreground overflow-hidden break-all space-y-2">
                <div><span className="text-muted-foreground inline-block w-20">url:</span> kylechoi101.github.io/surf-health/b/{beach.id}</div>
                <div><span className="text-muted-foreground inline-block w-20">og:title:</span> {shareTitle}</div>
                <div><span className="text-muted-foreground inline-block w-20">og:desc:</span> {displayCopy.body}</div>
                <div><span className="text-muted-foreground inline-block w-20">og:image:</span> /og/{beach.id}-{shareImageSlug}.png</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function PhoneMock({
  beach,
  band,
  displayCopy,
  signalText,
  p,
  pLabel,
  conditions,
}: {
  beach: BeachSummary;
  band: ForecastRecord["risk_band"];
  displayCopy: ReturnType<typeof forecastDisplayCopy>;
  signalText: string;
  p: number;
  pLabel: string;
  conditions: ConditionCard[];
}) {
  // Use explicit hex colors for the phone mock to maintain the "dark mode" preview aesthetic
  // regardless of the site's current theme, as this represents a native iOS app preview.
  const isGood = band === 'Low';
  const headerBg = isGood ? '#047857' : (band === 'Moderate' ? '#b45309' : '#b91c1c');
  
  return (
    <div className="w-[340px] shrink-0 rounded-[2.5rem] bg-[#1a1a1a] p-2 shadow-2xl relative overflow-hidden ring-1 ring-white/10">
      <div className="rounded-[2rem] bg-[#f8fafc] overflow-hidden relative h-[600px] flex flex-col">
        {/* Status bar */}
        <div className="flex justify-between items-center px-6 pt-4 pb-2 font-mono text-[10px] font-semibold text-slate-900 z-20">
          <span>9:41</span>
          <span className="tracking-widest">● ●</span>
        </div>

        {/* Hero band */}
        <div className="relative px-6 pb-8 pt-4 shrink-0" style={{ backgroundColor: headerBg }}>
          <div className="font-mono text-[8px] font-bold tracking-[0.2em] text-white/90">SHORELIFE</div>
          <div className="font-mono text-[8px] text-white/70 tracking-widest uppercase mt-5 mb-1">
            {displayCopy.eyebrow}
          </div>
          <div className="text-5xl font-light text-white leading-none tracking-tight mb-2">
            {displayCopy.headline}
          </div>
          <div className="text-[11px] text-white/90 leading-relaxed font-sans max-w-[250px]">
            {displayCopy.body}
          </div>
          <div className="mt-5 font-mono text-[8px] font-bold text-white/90 tracking-wider uppercase">
            {beach.name} · {beach.county}
          </div>
        </div>

        {/* Risk readout card */}
        <div className="px-4 -mt-3 relative z-10">
          <div className="bg-white rounded-2xl p-5 shadow-sm ring-1 ring-slate-100">
            <div className="flex justify-between items-start">
              <div>
                <div className="text-slate-500 text-[8px] font-mono uppercase font-bold tracking-wider mb-1">Water quality</div>
                <div className="text-lg font-semibold text-slate-900">{band}</div>
                <div className="text-[10px] text-slate-500 mt-1 font-sans">Signal: {signalText}</div>
              </div>
              <div className="text-right">
                <div className="text-3xl text-slate-900 leading-none font-light">
                  {p}<span className="text-sm ml-0.5">%</span>
                </div>
                <div className="text-slate-400 text-[8px] mt-1.5 font-mono uppercase font-bold tracking-wider">{pLabel}</div>
              </div>
            </div>
            <div className="mt-4"><SeverityBar band={band} width="100%" height={4}/></div>
          </div>
        </div>

        {/* Conditions */}
        <div className="px-4 mt-4">
          <div className="text-slate-400 text-[8px] font-mono uppercase font-bold tracking-wider mb-2 px-1">Conditions</div>
          <div className="grid grid-cols-2 gap-2">
            {conditions.map((c) => (
              <div key={c.l} className="bg-white rounded-xl ring-1 ring-slate-100 p-3 shadow-sm">
                <div className="text-slate-400 text-[7px] font-mono uppercase font-bold tracking-wider mb-1">{c.l}</div>
                <div className="text-sm font-semibold text-slate-900">{c.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="px-4 mt-auto mb-6">
          <div className="bg-slate-900 rounded-xl p-4 text-center shadow-lg">
            <div className="text-xs font-semibold text-white mb-1">Daily coast forecast</div>
            <div className="text-[9px] text-slate-400">
              Latest sample · {formatPacificDate(beach.latest_official_sample_at)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
