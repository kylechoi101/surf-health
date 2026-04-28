"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Activity, Database, Globe, CheckCircle2, ShieldCheck } from "lucide-react";
import { getSystemHealth, HealthResponse } from "@/lib/api";

export function ShorelifeResearch() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getSystemHealth()
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  const model = health?.model_registry.production_model;
  const freshness = health?.pipeline_freshness;
  const sources = health?.source_freshness;
  const eligible = health?.model_registry?.public_release_eligible;

  return (
    <section id="research" className="py-24 bg-bone relative overflow-hidden border-b border-navy/5">
      <div className="max-w-7xl mx-auto px-6 relative z-10">
        <div className="grid lg:grid-cols-2 gap-20 items-center">
          <div className="max-w-xl">
            <span className="sl-eyebrow text-sun">03 · Operator View</span>
            <h2 className="sl-display text-4xl md:text-6xl mt-5 mb-8 text-primary leading-tight">
              Microbiology &amp;
              <span className="block italic text-navy/60">Model Traceability</span>
            </h2>
            <p className="text-foreground/70 leading-relaxed mb-10 text-lg">
              We monitor model registry status, source freshness, and spatial validation holdouts
              to ensure every forecast is backed by rigorous environmental context.
            </p>

            <div className="space-y-6">
              {[
                {
                  icon: Globe,
                  title: "Spatial Holdouts",
                  desc: "Models are validated against held-out coastal regions to ensure geographic generalization.",
                },
                {
                  icon: Activity,
                  title: "Calibration Gates",
                  desc: "Daily Brier-score and AUCPR audits prevent regressive model deployment.",
                },
                {
                  icon: Database,
                  title: "CDIP Integration",
                  desc: "Direct ingestion of nearshore wave models and NDBC buoy telemetry.",
                },
              ].map((item, i) => (
                <div key={i} className="flex gap-5 group">
                  <div className="shrink-0 w-10 h-10 rounded-lg bg-navy/5 flex items-center justify-center group-hover:bg-navy/10 transition-colors">
                    <item.icon className="w-5 h-5 text-navy" />
                  </div>
                  <div>
                    <h4 className="sl-label text-navy mb-1 lowercase font-semibold">{item.title}</h4>
                    <p className="text-[13px] text-muted-foreground leading-relaxed">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="relative">
            <div className="absolute inset-0 bg-navy/5 blur-3xl rounded-full -z-10" />
            <Card className="bg-bone/80 backdrop-blur-md border-navy/10 rounded-3xl shadow-2xl overflow-hidden">
              <CardContent className="p-0">
                <div className="p-8 bg-navy text-bone">
                  <div className="flex justify-between items-center mb-6">
                    <span className="sl-eyebrow text-bone/60">Pipeline Heartbeat</span>
                    <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-teal/20 text-teal border border-teal/30">
                      <span className="w-2 h-2 rounded-full bg-teal animate-pulse" />
                      <span className="sl-mono text-[9px] uppercase font-bold">
                        {error ? "Unavailable" : "Active"}
                      </span>
                    </div>
                  </div>
                  <div className="sl-display text-3xl mb-2">
                    {model ? `Model: ${model}` : error ? "Pipeline offline" : "Loading…"}
                  </div>
                  {freshness && (
                    <p className="sl-mono text-[11px] text-bone/60 lowercase tracking-widest">
                      Build {freshness}
                    </p>
                  )}
                </div>

                <div className="p-8 space-y-6">
                  {!error && (
                    <div>
                      <h5 className="sl-label text-muted-foreground mb-4 lowercase">Source Freshness</h5>
                      <div className="space-y-4">
                        {sources ? (
                          Object.entries(sources).map(([src, age]) => (
                            <div key={src} className="flex justify-between items-center">
                              <span className="text-[13px] text-navy font-medium">{src}</span>
                              <div className="flex items-center gap-3">
                                <span className="sl-mono text-[10px] text-muted-foreground">{age}</span>
                                <CheckCircle2 className="w-3.5 h-3.5 text-teal" />
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="sl-mono text-[10px] text-muted-foreground">
                            {health === null ? "Fetching…" : "No source data"}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {eligible !== undefined && (
                    <div className="pt-6 border-t border-navy/5">
                      <div className="flex justify-between items-center">
                        <div>
                          <h5 className="sl-label text-muted-foreground mb-1 lowercase">Public Eligibility</h5>
                          <div className="text-xl sl-display text-navy">
                            {eligible ? "Eligible for Release" : "Pending Validation"}
                          </div>
                        </div>
                        <div className="w-12 h-12 rounded-full bg-teal/10 flex items-center justify-center">
                          <ShieldCheck className="w-6 h-6 text-teal" />
                        </div>
                      </div>
                    </div>
                  )}

                  {error && (
                    <div className="sl-mono text-[10px] text-muted-foreground text-center py-4">
                      Pipeline health unavailable — check back after the 6 AM run.
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </section>
  );
}
