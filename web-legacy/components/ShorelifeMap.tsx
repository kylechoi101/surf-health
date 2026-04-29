"use client";

import React, { useEffect, useState } from "react";
import { CaliforniaPosterMap, BeachStation } from "./CaliforniaPosterMap";
import { getBeaches } from "@/lib/api";

export function ShorelifeMap() {
  const [beaches, setBeaches] = useState<BeachStation[]>([]);
  const [activeBeach, setActiveBeach] = useState<BeachStation | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const [data, summary] = await Promise.all([
          getBeaches(),
          fetch('/forecast_summary.json').then(r => r.json()).catch(() => []),
        ]);
        const riskMap = new Map<string, { risk_band: string; wave_height_m: number | null; water_temperature_c: number | null }>(
          summary.map((r: any) => [r.beach_id, r])
        );
        const stations: BeachStation[] = data.map(b => {
          const f = riskMap.get(b.id);
          return {
            id: b.id,
            name: b.name,
            county: b.county,
            region: b.region,
            lat: b.geometry.latitude,
            lon: b.geometry.longitude,
            risk: f?.risk_band as BeachStation['risk'],
            waveFt: f?.wave_height_m != null ? parseFloat((f.wave_height_m * 3.281).toFixed(1)) : undefined,
            temp: f?.water_temperature_c != null ? Math.round(f.water_temperature_c * 9 / 5 + 32) : undefined,
          };
        });
        setBeaches(stations);
        const defaultBeach = stations.find(b => b.id === "ca738498-los-angeles-surfrider-beach-dph-002") || stations[0];
        setActiveBeach(defaultBeach);
      } catch (err) {
        console.error("Failed to fetch beaches for map section:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  return (
    <section id="map" className="py-24 bg-ecru relative border-y border-navy/5">
      <div className="max-w-7xl mx-auto px-6">
        {/* Section Header */}
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-10 mb-16">
          <div className="max-w-2xl">
            <span className="sl-eyebrow text-sun">
              02 · Interactive Map
            </span>
            <h2 className="sl-display text-4xl md:text-6xl mt-5 mb-6 text-primary leading-tight">
              California Coast
              <span className="block italic text-navy/60">Monitoring Network</span>
            </h2>
            <p className="text-foreground/70 leading-relaxed">
              Explore real-time water quality data from 300+ monitoring stations spanning 
              the entire California coastline. Hover or click for detailed regional forecasts.
            </p>
          </div>
          
          <div className="flex gap-12 pt-6 lg:pt-0">
            <div className="text-left">
              <div className="sl-display text-4xl text-navy">{beaches.length}</div>
              <div className="sl-label text-muted-foreground mt-2 lowercase">Active Sites</div>
            </div>
            <div className="text-left">
              <div className="sl-display text-4xl text-navy">840</div>
              <div className="sl-label text-muted-foreground mt-2 lowercase">Miles of Coast</div>
            </div>
            <div className="text-left">
              <div className="sl-display text-4xl text-navy">6hr</div>
              <div className="sl-label text-muted-foreground mt-2 lowercase">Update Cycle</div>
            </div>
          </div>
        </div>

        {/* Map Container */}
        <div
          className="h-[600px] md:h-[800px] bg-bone border border-navy/10 rounded-3xl overflow-hidden shadow-xl relative"
          onMouseLeave={() => setActiveBeach(null)}
        >
          <CaliforniaPosterMap
            beaches={beaches}
            activeBeach={activeBeach || undefined}
            onSelect={setActiveBeach}
            height={800}
            className="w-full"
          />

          {/* Loading shimmer */}
          {loading && (
            <div className="absolute inset-0 flex items-end justify-center pb-12 pointer-events-none">
              <div className="sl-mono text-[10px] text-navy/40 animate-pulse tracking-widest uppercase">
                Loading stations…
              </div>
            </div>
          )}

          {/* Annotation Overlay */}
          <div className="absolute top-8 left-8 pointer-events-none">
            <div className="sl-label text-[10px] text-navy/40">FIG. 01 · STATEWIDE HEALTH BOARD</div>
          </div>
        </div>
        
        <div className="mt-8 flex justify-between items-center px-4">
          <div className="sl-mono text-[10px] text-muted-foreground tracking-widest uppercase italic">
            Lat/Lon → Viewport projection v1.0
          </div>
          <div className="sl-label text-navy/40 text-[9px]">Hover stations for rapid telemetry readout →</div>
        </div>
      </div>
    </section>
  );
}
