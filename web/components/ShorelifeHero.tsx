"use client";

import React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LockupHorizontal } from "@/components/Lockup";
import { ChevronDown, Thermometer, Waves, ShieldCheck } from "lucide-react";

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
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-20">
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

        {/* Key Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 max-w-4xl mx-auto pt-10 border-t border-navy/5">
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <Thermometer className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <h3 className="sl-label text-navy mb-2">Real-time Data</h3>
            <p className="text-[13px] text-muted-foreground leading-relaxed">NDBC Buoys, CDIP models, and NWS grids updated hourly.</p>
          </div>
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <ShieldCheck className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <h3 className="sl-label text-navy mb-2">Validated Risk</h3>
            <p className="text-[13px] text-muted-foreground leading-relaxed">ML-driven probability estimates calibrated against culture samples.</p>
          </div>
          <div className="text-center group">
            <div className="w-12 h-12 mx-auto mb-5 rounded-xl bg-bone border border-navy/10 flex items-center justify-center group-hover:border-sun/30 transition-colors shadow-sm">
              <Waves className="w-5 h-5 text-navy group-hover:text-sun transition-colors" />
            </div>
            <h3 className="sl-label text-navy mb-2">Surf Context</h3>
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
