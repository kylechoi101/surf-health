"use client";

import { CoastalMap } from "@/components/coastal-map";

export function MapSection() {
  return (
    <section id="map" className="py-24 bg-muted/30 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6 mb-12">
          <div className="max-w-2xl">
            <span className="text-primary text-sm tracking-widest uppercase font-medium">
              Interactive Map
            </span>
            <h2 className="text-3xl md:text-4xl font-light mt-4 mb-4 text-foreground text-balance">
              California Coast
              <span className="font-semibold"> Monitoring Network</span>
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              Explore real-time water quality data from monitoring stations spanning 
              the entire California coastline. Click any marker for detailed forecasts.
            </p>
          </div>
          
          <div className="flex gap-8 text-sm">
            <div className="text-center">
              <div className="text-2xl font-semibold text-foreground">21</div>
              <div className="text-muted-foreground">Active Sites</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-semibold text-foreground">840</div>
              <div className="text-muted-foreground">Miles of Coast</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-semibold text-foreground">6hr</div>
              <div className="text-muted-foreground">Update Cycle</div>
            </div>
          </div>
        </div>

        {/* Map */}
        <div className="h-[550px] md:h-[650px]">
          <CoastalMap />
        </div>
      </div>
    </section>
  );
}
