"use client";

import React, { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/header";
import { 
  RiskBand, 
  RISK_COPY, 
  RISK_TOKEN, 
  DropRow, 
  SeverityBar, 
  RiskChip 
} from "@/components/RiskComponents";
import { 
  getForecast, 
  getBeaches, 
  preferredForecastDate, 
  BeachSummary, 
  ForecastRecord 
} from "@/lib/api";

function SharePageContent() {
  const searchParams = useSearchParams();
  const beachId = searchParams.get("id") || "malibu";
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const [beaches, f] = await Promise.all([
          getBeaches(),
          getForecast(beachId, preferredForecastDate())
        ]);
        const b = beaches.find(b => b.id === beachId) || beaches[0];
        setBeach(b);
        setForecast(f);
      } catch (err) {
        console.error("Failed to fetch beach data:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [beachId]);

  if (loading || !beach || !forecast) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="sl-display animate-pulse text-4xl text-primary opacity-20">shorelife</div>
      </div>
    );
  }

  const band = forecast.risk_band;
  const tok = RISK_TOKEN[band];
  const copy = RISK_COPY[band];

  // Map API units to display units
  const waveFt = Math.round((forecast.environmental_summary.wave_height_m || 0) * 3.28084);
  const tempF = Math.round(((forecast.environmental_summary.water_temperature_c || 0) * 9/5) + 32);
  const windMph = Math.round((forecast.environmental_summary.wind_speed_mps || 0) * 2.23694);

  return (
    <div className="px-6 py-12 md:px-16 md:py-12 max-w-7xl mx-auto">
      <Header />

      <div className="pt-20 pb-6">
        <div className="sl-eyebrow text-accent">Beach · share preview</div>
        <h1 className="sl-display text-5xl md:text-7xl mt-3 mb-4 text-primary">
          {beach.name}
        </h1>
        <div className="flex flex-wrap gap-x-6 gap-y-2 items-baseline font-mono text-[11px] tracking-widest text-muted-foreground uppercase">
          <span>{beach.county} County</span>
          <span>·</span>
          <span>{beach.region}</span>
          <span>·</span>
          <span>
            {beach.geometry.latitude.toFixed(3)}°N · {Math.abs(beach.geometry.longitude).toFixed(3)}°W
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-12 items-start">
        {/* LEFT — full beach detail */}
        <div>
          {/* Big risk hero card */}
          <div 
            className="relative rounded-2xl p-8 md:p-10 overflow-hidden border"
            style={{ background: tok.bg, borderColor: tok.c }}
          >
            {/* Tide-line texture */}
            <svg 
              className="absolute inset-0 w-full h-full opacity-20"
              viewBox="0 0 600 320" 
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {[60, 90, 130, 180, 240].map((y, i) => (
                <path 
                  key={i} 
                  d={`M 0 ${y} C 150 ${y - 6}, 300 ${y + 8}, 450 ${y - 4} S 600 ${y}, 600 ${y}`}
                  stroke={tok.ink} 
                  strokeWidth="1" 
                  fill="none" 
                  opacity={1 - i * 0.15}
                />
              ))}
            </svg>
            
            <div className="relative z-10">
              <div className="flex items-center gap-3">
                <DropRow band={band} size={18} />
                <div className="sl-label" style={{ color: tok.ink }}>{band.toUpperCase()} · TODAY</div>
              </div>
              <div 
                className="sl-display text-8xl md:text-[120px] leading-[0.85] mt-5 mb-4"
                style={{ color: tok.ink }}
              >
                {copy.head}
              </div>
              <div 
                className="text-lg md:text-xl opacity-85 leading-relaxed max-w-lg"
                style={{ color: tok.ink }}
              >
                {copy.sub}
              </div>
              
              <div 
                className="mt-8 pt-6 border-t border-dashed flex justify-between gap-4"
                style={{ borderColor: tok.c }}
              >
                <div>
                  <div className="sl-label opacity-70" style={{ color: tok.ink }}>Enterococcus</div>
                  <div className="sl-mono text-lg mt-1" style={{ color: tok.ink }}>{copy.cfu}</div>
                </div>
                <div className="text-center">
                  <div className="sl-label opacity-70" style={{ color: tok.ink }}>Exceed chance</div>
                  <div className="sl-display text-4xl mt-1 leading-none" style={{ color: tok.ink }}>
                    {Math.round(forecast.p_exceed * 100)}<span className="text-lg">%</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="sl-label opacity-70" style={{ color: tok.ink }}>Sampled</div>
                  <div className="sl-mono text-lg mt-1" style={{ color: tok.ink }}>
                    {forecast.forecast_age_hours ? `${Math.round(forecast.forecast_age_hours / 24)}d ago` : "Live"}
                  </div>
                </div>
              </div>
              
              <div className="mt-4">
                <SeverityBar band={band} className="w-full" />
              </div>
            </div>
          </div>

          {/* Conditions strip */}
          <div className="mt-8">
            <div className="sl-eyebrow text-accent">Conditions now</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
              {[
                { l: "Surf",  v: `${waveFt}ft`, s: `@ ${forecast.environmental_summary.dominant_period_s}s` },
                { l: "Water", v: `${tempF}°F`,    s: tempF > 65 ? "mild" : "chilly" },
                { l: "Wind",  v: `${windMph} mph`,  s: "NW" },
                { l: "UV",    v: forecast.environmental_summary.uv_index || 0, s: (forecast.environmental_summary.uv_index || 0) >= 7 ? "high" : "moderate" },
              ].map(c => (
                <div key={c.l} className="bg-bone border border-border rounded-xl p-5">
                  <div className="sl-label text-muted-foreground">{c.l}</div>
                  <div className="sl-display text-3xl mt-2 text-primary">{c.v}</div>
                  <div className="sl-mono text-[11px] text-muted-foreground mt-1">{c.s}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Drivers */}
          <div className="mt-8">
            <div className="sl-eyebrow text-accent">What's driving this</div>
            <div className="mt-4 bg-bone border border-border rounded-2xl overflow-hidden">
              {forecast.top_drivers.slice(0, 4).map((d, i) => (
                <div 
                  key={i} 
                  className={`p-4 md:p-5 flex gap-4 ${i !== 0 ? "border-t border-border/30" : ""}`}
                >
                  <span 
                    className="w-6 h-6 rounded-md flex items-center justify-center font-mono text-[11px] font-bold shrink-0"
                    style={{ background: tok.bg, color: tok.ink }}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <p className="m-0 text-sm md:text-base text-foreground leading-relaxed">{d}</p>
                </div>
              ))}
              {forecast.top_drivers.length === 0 && (
                <div className="p-5 text-muted-foreground text-center font-mono text-sm uppercase tracking-widest">
                  No dominant environmental drivers today.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT — phone preview + share metadata */}
        <div className="space-y-8">
          <div>
            <div className="sl-eyebrow text-accent">iOS share preview</div>
            <div className="mt-4 p-6 bg-bone border border-border rounded-2xl flex justify-center">
              <PhoneMock beach={beach} forecast={forecast} />
            </div>
          </div>

          <div>
            <div className="sl-eyebrow text-accent">Share link metadata</div>
            <div className="mt-4 font-mono text-[12px] text-foreground bg-bone border border-border rounded-xl p-4 leading-relaxed overflow-x-auto">
              <div><span className="text-muted-foreground">url:</span> kylechoi101.github.io/surf-health/b?id={beach.id}</div>
              <div><span className="text-muted-foreground">og:title:</span> {beach.name} · {copy.head}</div>
              <div><span className="text-muted-foreground">og:desc:</span> {copy.sub}</div>
              <div className="truncate"><span className="text-muted-foreground ">og:image:</span> /og/{beach.id}-{band.toLowerCase().replace(/\s+/g, "-")}.png</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PhoneMock({ beach, forecast }: { beach: BeachSummary, forecast: ForecastRecord }) {
  const band = forecast.risk_band;
  const tok = RISK_TOKEN[band];
  const copy = RISK_COPY[band];
  
  const waveFt = Math.round((forecast.environmental_summary.wave_height_m || 0) * 3.28084);
  const tempF = Math.round(((forecast.environmental_summary.water_temperature_c || 0) * 9/5) + 32);
  const windMph = Math.round((forecast.environmental_summary.wind_speed_mps || 0) * 2.23694);

  return (
    <div className="w-[300px] md:w-[340px] rounded-[38px] bg-[#1a1a1a] p-2 shadow-2xl scale-90 md:scale-100 origin-top">
      <div className="rounded-[32px] bg-background overflow-hidden relative h-[560px] md:h-[600px] flex flex-col">
        {/* Status bar */}
        <div className="flex justify-between px-6 pt-3.5 pb-2 font-mono text-[10px] font-bold text-foreground">
          <span>9:41</span>
          <span className="space-x-1">● ●</span>
        </div>

        {/* Hero band */}
        <div 
          className="px-6 pt-5 pb-6 relative overflow-hidden"
          style={{ background: tok.c }}
        >
          <div className="font-mono text-[9px] font-bold tracking-[0.18em] text-white/85">SHORELIFE</div>
          <div className="font-mono text-[9px] text-white/70 tracking-widest uppercase mt-4">
            Can I swim today?
          </div>
          <div className="sl-display text-5xl text-white mt-1">
            {copy.head}
          </div>
          <div className="text-[12px] text-white/90 mt-2 leading-relaxed">
            {copy.sub}
          </div>
          <div className="mt-4 font-mono text-[10px] font-bold text-white/90 tracking-wider">
            {beach.name.toUpperCase()} · {beach.county.toUpperCase()}
          </div>
        </div>

        {/* Risk readout card */}
        <div className="px-3.5 pt-3.5">
          <div className="rounded-2xl p-4" style={{ background: tok.bg }}>
            <div className="flex justify-between items-start">
              <div>
                <div className="sl-label text-[9px]" style={{ color: tok.ink }}>Water quality</div>
                <div className="text-lg font-bold mt-1" style={{ color: tok.ink }}>{band}</div>
                <div className="text-[11px] mt-1 opacity-80" style={{ color: tok.ink }}>Ent: {copy.cfu}</div>
              </div>
              <div className="text-right">
                <div className="sl-display text-3xl leading-none" style={{ color: tok.ink }}>
                  {Math.round(forecast.p_exceed * 100)}<span className="text-sm">%</span>
                </div>
                <div className="sl-label opacity-70 text-[9px] mt-1" style={{ color: tok.ink }}>EXCEED</div>
              </div>
            </div>
            <div className="mt-3">
              <SeverityBar band={band} className="w-full h-1.5" />
            </div>
          </div>
        </div>

        {/* Conditions */}
        <div className="px-3.5 pt-3.5 flex-1">
          <div className="sl-label text-muted-foreground text-[9px]">Conditions</div>
          <div className="grid grid-cols-2 gap-1.5 mt-2">
            {[
              { l: "Surf",  v: `${waveFt}ft` },
              { l: "Water", v: `${tempF}°F` },
              { l: "Wind",  v: `${windMph} mph` },
              { l: "UV",    v: forecast.environmental_summary.uv_index || 0 },
            ].map(c => (
              <div key={c.l} className="bg-bone rounded-xl border border-border p-2.5">
                <div className="sl-label text-muted-foreground text-[8px]">{c.l}</div>
                <div className="text-base font-bold text-primary mt-0.5">{c.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="p-3.5 mt-2">
          <div className="bg-primary rounded-2xl py-3 px-4 text-center">
            <div className="text-[13px] font-bold text-bone">Get the Shorelife app</div>
            <div className="text-[10px] text-bone/70 mt-0.5">300+ California beaches</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SharePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="sl-display animate-pulse text-4xl text-primary opacity-20">shorelife</div>
      </div>
    }>
      <SharePageContent />
    </Suspense>
  );
}
