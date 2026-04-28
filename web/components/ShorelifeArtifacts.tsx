"use client";

import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { ExternalLink } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://surf-health-api.onrender.com";

const artifacts = [
  {
    type: "API",
    title: "Live Forecast API",
    description:
      "RESTful endpoint serving daily bacteria-risk forecasts for 300+ California beaches. Includes environmental context, top risk drivers, and calibrated exceedance probability.",
    href: API_BASE,
    external: true,
  },
  {
    type: "Document",
    title: "Model Methodology",
    description:
      "Spatial cross-validation protocol, feature rationale (UV, wind, pier proximity, enterococcus history), known failure modes, and calibration discussion.",
    href: "/methodology",
    external: false,
  },
  {
    type: "Research",
    title: "Pipeline & Data Sources",
    description:
      "Registry health, source freshness, and holdout validation metrics for the current production model — updated each morning after the daily forecast run.",
    href: "/research",
    external: false,
  },
];

const typeColors: Record<string, string> = {
  API: "bg-teal/10 text-teal-deep",
  Document: "bg-navy/10 text-navy",
  Research: "bg-sun/10 text-sun-deep",
};

export function ShorelifeArtifacts() {
  return (
    <section id="artifacts" className="py-24 bg-ecru relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 relative z-10">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-10 mb-16">
          <div className="max-w-2xl">
            <span className="sl-eyebrow text-sun">04 · Resources</span>
            <h2 className="sl-display text-4xl md:text-6xl mt-5 mb-6 text-primary leading-tight">
              Data &amp; Documentation
              <span className="block italic text-navy/60">Open Access</span>
            </h2>
            <p className="text-foreground/70 leading-relaxed max-w-xl">
              API access, methodology documentation, and pipeline transparency — all public.
            </p>
          </div>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
          {artifacts.map((artifact) => (
            <a
              key={artifact.title}
              href={artifact.href}
              target={artifact.external ? "_blank" : undefined}
              rel={artifact.external ? "noopener noreferrer" : undefined}
              className="block group"
            >
              <Card className="h-full bg-bone border-navy/10 hover:border-navy/30 hover:shadow-xl transition-all duration-300 rounded-2xl overflow-hidden">
                <CardContent className="p-8 flex flex-col h-full">
                  <span
                    className={`sl-label text-[9px] inline-block px-3 py-1 rounded-full mb-6 ${typeColors[artifact.type]}`}
                  >
                    {artifact.type}
                  </span>
                  <h3 className="sl-display text-xl mb-4 text-navy leading-tight group-hover:text-sun transition-colors">
                    {artifact.title}
                  </h3>
                  <p className="text-muted-foreground text-sm leading-relaxed flex-1">
                    {artifact.description}
                  </p>
                  <div className="flex items-center gap-2 mt-8 pt-6 border-t border-navy/5">
                    <span className="sl-label text-[10px] text-navy group-hover:text-sun transition-colors">
                      {artifact.external ? "Open" : "Read"}
                    </span>
                    <ExternalLink className="w-3 h-3 text-navy group-hover:text-sun transition-colors" />
                  </div>
                </CardContent>
              </Card>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
