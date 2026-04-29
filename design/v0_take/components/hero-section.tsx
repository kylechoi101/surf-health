"use client";

import { Button } from "@/components/ui/button";
import { ShoreLifeLogo } from "@/components/shorelife-logo";
import { ChevronDown, Thermometer, Waves, Bug } from "lucide-react";

export function HeroSection() {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden bg-gradient-to-b from-[#0c4a6e] via-[#0e7490] to-[#14b8a6]">
      {/* Subtle wave pattern background */}
      <div className="absolute inset-0 opacity-10">
        <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 1440 800">
          <path
            d="M0 400 Q360 300 720 400 T1440 400 V800 H0 Z"
            fill="currentColor"
            className="text-white"
          />
          <path
            d="M0 450 Q360 350 720 450 T1440 450 V800 H0 Z"
            fill="currentColor"
            className="text-white"
            opacity="0.5"
          />
        </svg>
      </div>

      {/* Gradient overlay */}
      <div className="absolute bottom-0 left-0 right-0 h-48 bg-gradient-to-t from-background to-transparent" />

      {/* Content */}
      <div className="relative z-20 max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 text-center">
        {/* Logo */}
        <div className="flex justify-center mb-8">
          <ShoreLifeLogo size={120} className="drop-shadow-2xl" />
        </div>

        {/* Headline */}
        <h1 className="text-4xl sm:text-5xl md:text-6xl font-light leading-tight mb-6 text-white tracking-wide text-balance">
          California Coastal
          <span className="block font-semibold mt-2">Water Quality Monitor</span>
        </h1>

        {/* Subheadline */}
        <p className="text-lg sm:text-xl text-white/80 mb-12 max-w-2xl mx-auto leading-relaxed font-light text-balance">
          Real-time forecasting of water temperature, wave conditions, and bacterial levels 
          across California&apos;s coastline for researchers and public health.
        </p>

        {/* CTA Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-20">
          <Button
            size="lg"
            className="bg-white hover:bg-white/90 text-[#0c4a6e] text-base px-8 py-6 rounded-sm"
          >
            View Forecast Map
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="bg-transparent hover:bg-white/10 border-white/40 text-white text-base px-8 py-6 rounded-sm"
          >
            Access Research Data
          </Button>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-3xl mx-auto">
          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-white/10 flex items-center justify-center">
              <Thermometer className="w-5 h-5 text-white" />
            </div>
            <h3 className="text-white font-medium mb-1">Temperature</h3>
            <p className="text-white/60 text-sm">Real-time water temperature data</p>
          </div>
          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-white/10 flex items-center justify-center">
              <Waves className="w-5 h-5 text-white" />
            </div>
            <h3 className="text-white font-medium mb-1">Wave Height</h3>
            <p className="text-white/60 text-sm">Current swell and surf conditions</p>
          </div>
          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-white/10 flex items-center justify-center">
              <Bug className="w-5 h-5 text-white" />
            </div>
            <h3 className="text-white font-medium mb-1">Bacteria Levels</h3>
            <p className="text-white/60 text-sm">Microbial water quality indicators</p>
          </div>
        </div>
      </div>

      {/* Scroll Indicator */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-20 animate-bounce">
        <a
          href="#forecast"
          className="flex flex-col items-center text-white/50 hover:text-white transition-colors"
        >
          <span className="text-xs tracking-widest uppercase mb-2">Explore</span>
          <ChevronDown className="w-5 h-5" />
        </a>
      </div>
    </section>
  );
}
