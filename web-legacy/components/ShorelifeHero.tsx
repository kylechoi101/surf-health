"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LockupHorizontal } from "@/components/Lockup";
import { ChevronDown, Thermometer, Waves, ShieldCheck, ArrowRight } from "lucide-react";
import { RiskChip, RISK_TOKEN, type RiskBand } from "@/components/RiskComponents";

const SPOTLIGHT_ID = "ca738498-los-angeles-surfrider-beach-dph-002";
const SPOTLIGHT_NAME = "Surfrider Beach";
const SPOTLIGHT_LOCATION = "Malibu · Los Angeles County";

interface SpotlightData {
  beach_id: string;
  risk_band: RiskBand;
  p_exceed: number;
  wave_height_m: number | null;
  water_temperature_c: number | null;
}

function mToFt(m: number | null): string {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

function cToF(c: number | null): string {
  if (c == null) return "—";
  return Math.round(c * 9 / 5 + 32) + "°F";
}

function SpotlightCard() {
  const [data, setData] = useState<SpotlightData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/forecast_summary.json")
      .then(r => r.json())
      .then((rows: SpotlightData[]) => {
        const match = rows.find(r => r.beach_id === SPOTLIGHT_ID) ?? rows[0];
        setData(match ?? null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const tok = data ? RISK_TOKEN[data.risk_band] : null;

  return (
    <Link
      href={`/beaches/${SPOTLIGHT_ID}`}
      className="group inline-flex items-center gap-5 mt-12 mb-10 px-6 py-4 rounded-2xl border border-navy/10 bg-bone/60 hover:bg-bone hover:border-navy/20 backdrop-blur-sm transition-all shadow-sm hover:shadow-md"
    >
      <div className="text-left">
        <div className="sl-eyebrow text-navy/40 text-[9px] mb-0.5">Today at</div>
        <div className="sl-display text-base text-navy leading-tight">{SPOTLIGHT_NAME}</div>
        <div className="sl-label text-muted-foreground text-[10px] mt-0.5 lowercase">{SPOTLIGHT_LOCATION}</div>
      </div>

      <div className="w-px h-10 bg-navy/10 mx-1 shrink-0" />

      {loading ? (
        <div className="flex gap-3 items-center">
          <div className="h-6 w-16 bg-navy/5 rounded-full animate-pulse" />
          <div className="h-3 w-20 bg-navy/5 rounded animate-pulse" />
        </div>
      ) : data ? (
        <>
          <RiskChip band={data.risk_band} />
          <div className="text-left">
            <div className="sl-mono text-xs font-semibold" style={{ color: tok?.c }}>
              {Math.round(data.p_exceed * 100)}% exceedance
            </div>
            <div className="sl-mono text-[10px] text-muted-foreground mt-0.5">
              {mToFt(data.wave_height_m)} swell · {cToF(data.water_temperature_c)}
            </div>
          </div>
        </>
      ) : (
        <span className="sl-label text-muted-foreground text-[10px] lowercase">Forecast unavailable</span>
      )}

      <ArrowRight className="w-3.5 h-3.5 text-navy/30 group-hover:text-navy group-hover:translate-x-0.5 transition-all ml-1 shrink-0" />
    </Link>
  );
}

export function ShorelifeHero() {
  return (
    <section className="relative min-h-[90vh] flex items-center justify-center overflow-hidden bg-ecru">
      {/* Decorative sun element (poster style) */}
      <div className="absolute top-[-10%] right-[-5%] w-[400px] h-[400px] rounded-full bg-sun/10 blur-3xl animate-pulse"></div>
      <div className="absolute bottom-[-10%] left-[-5%] w-[300px] h-[300px] rounded-full bg-navy/5 blur-3xl"></div>

      {/* Content */}
      <div className="relative z-20 max-w-5xl mx-auto px-6 pt-20 text-center">
        {/* Brand Mark */}
        <div className="flex justify-center mb-10 animate-float">
          <LockupHorizontal size={48} subtitle="California" />
        </div>

        {/* Headline - Editorial Serif */}
        <h1 className="sl-display text-5xl md:text-8xl mb-8 text-primary leading-tight text-balance">
          Know before you
          <span className="block italic text-sun mt-2">paddle out.</span>
        </h1>

        {/* Subheadline - Clean Sans */}
        <p className="text-lg md:text-xl text-foreground/80 mb-12 max-w-2xl mx-auto leading-relaxed font-light text-balance">
          Shorelife turns sparse official bacteria samples plus ocean and weather context into a 
          daily health-risk forecast for <span className="text-navy font-medium">300+ California marine beaches</span>.
        </p>

        {/* CTA Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-0">
          <Button
            asChild
            size="lg"
            className="bg-navy hover:bg-navy-deep text-bone text-xs sl-label px-10 py-7 rounded-full shadow-lg hover:shadow-xl transition-all"
          >
            <Link href="#forecast">View Live Forecast</Link>
          </Button>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="bg-transparent border-navy/20 text-navy hover:bg-navy/5 text-xs sl-label px-10 py-7 rounded-full transition-all"
          >
            <Link href="/methodology">Read Methodology</Link>
          </Button>
        </div>

        {/* Spotlight Beach */}
        <div className="flex justify-center">
          <SpotlightCard />
        </div>

        {/* Key Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 max-w-4xl mx-auto pt-10 border-t border-navy/5">
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <Thermometer className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <p className="sl-label text-navy mb-2">Real-time Data</p>
            <p className="text-[13px] text-muted-foreground leading-relaxed">NDBC Buoys, CDIP models, and NWS grids updated hourly.</p>
          </div>
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <ShieldCheck className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <p className="sl-label text-navy mb-2">Validated Risk</p>
            <p className="text-[13px] text-muted-foreground leading-relaxed">ML-driven probability estimates calibrated against culture samples.</p>
          </div>
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <Waves className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <p className="sl-label text-navy mb-2">Surf Context</p>
            <p className="text-[13px] text-muted-foreground leading-relaxed">Integrated swell, tide, and UV data for a complete beach profile.</p>
          </div>
        </div>
      </div>

      {/* Scroll Indicator */}
      <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-20">
        <Link
          href="#forecast"
          className="flex flex-col items-center text-navy/30 hover:text-navy transition-colors animate-bounce"
        >
          <span className="sl-label text-[9px] mb-2">Explore</span>
          <ChevronDown className="w-4 h-4" />
        </Link>
      </div>
    </section>
  );
}
