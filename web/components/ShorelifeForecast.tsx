"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowRight } from "lucide-react";
import { RiskChip, RISK_TOKEN, type RiskBand } from "@/components/RiskComponents";

const SPOTLIGHT = [
  { id: "ca549911-east-bay-parks-district-crown-beach-alameda-co-crown-bath-house", name: "Crown Beach", county: "Alameda", region: "Bay Area" },
  { id: "ca905766-santa-cruz-main-beach-main", name: "Santa Cruz Main Beach", county: "Santa Cruz", region: "Central Coast" },
  { id: "ca738498-los-angeles-surfrider-beach-dph-002", name: "Surfrider Beach", county: "Los Angeles", region: "Southern California" },
  { id: "ca799523-san-diego-ocean-beach-pl-080", name: "Ocean Beach", county: "San Diego", region: "Southern California" },
];

interface ForecastSummary {
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

export function ShorelifeForecast() {
  const [forecasts, setForecasts] = useState<Map<string, ForecastSummary>>(new Map());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/forecast_summary.json")
      .then(r => r.json())
      .then((data: ForecastSummary[]) => setForecasts(new Map(data.map(r => [r.beach_id, r]))))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <section id="forecast" className="py-24 bg-bone relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 relative z-10">
        <div className="max-w-3xl mb-16">
          <span className="sl-eyebrow text-sun">01 · Today's Forecast</span>
          <h2 className="sl-display text-4xl md:text-6xl mt-5 mb-8 text-primary leading-tight">
            California Coastal
            <span className="block italic text-navy/60">Water Quality</span>
          </h2>
          <p className="text-foreground/70 leading-relaxed max-w-xl">
            Daily bacteria forecasts for 300+ beaches, updated each morning from CDPH, NDBC, and CDIP data sources.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-8">
          {SPOTLIGHT.map((beach) => {
            const f = forecasts.get(beach.id);
            return (
              <Card
                key={beach.id}
                className="bg-bone border-border/60 hover:border-navy/20 transition-all shadow-sm hover:shadow-md rounded-2xl overflow-hidden group"
              >
                <CardContent className="p-0">
                  <div className="p-8">
                    <div className="sl-eyebrow text-muted-foreground mb-2 lowercase">{beach.region} · {beach.county}</div>
                    <h3 className="sl-display text-2xl text-navy">{beach.name}</h3>

                    <div className="mt-6 flex items-center gap-4">
                      {loading ? (
                        <span className="sl-display text-4xl text-navy/20">—</span>
                      ) : f ? (
                        <>
                          <RiskChip band={f.risk_band} />
                          <div className="flex flex-col">
                            <span className="sl-mono text-sm text-navy font-semibold">
                              {Math.round(f.p_exceed * 100)}% exceedance probability
                            </span>
                            <span className="sl-mono text-[10px] text-muted-foreground mt-0.5">
                              {mToFt(f.wave_height_m)} · {cToF(f.water_temperature_c)}
                            </span>
                          </div>
                        </>
                      ) : (
                        <span className="sl-label text-muted-foreground lowercase">No forecast available</span>
                      )}
                    </div>
                  </div>
                  <Link
                    href={`/beaches/${beach.id}`}
                    className="flex items-center justify-between px-8 py-4 bg-navy/5 hover:bg-navy/10 transition-colors"
                  >
                    <span className="sl-label text-navy text-[10px] lowercase">View station</span>
                    <ArrowRight className="w-3.5 h-3.5 text-navy group-hover:translate-x-1 transition-transform" />
                  </Link>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </section>
  );
}
