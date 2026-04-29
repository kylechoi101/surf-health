"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { 
  FileText, 
  ExternalLink,
  Code,
  Activity,
  LineChart,
  ShieldCheck,
  BookOpen
} from "lucide-react";
import Link from "next/link";

const artifacts = [
  {
    type: "Documentation",
    title: "Methodology",
    icon: BookOpen,
    description: "Detailed breakdown of our predictive models, including BeachTCN architecture and logistic baselines.",
    href: "/methodology",
    external: false
  },
  {
    type: "API",
    title: "Model Registry",
    icon: Activity,
    description: "Live snapshot of the production model version and candidate models in staging.",
    href: "https://raw.githubusercontent.com/kylechoi101/surf-health/main/data/curated/model_version.json",
    external: true
  },
  {
    type: "Codebase",
    title: "GitHub Repository",
    icon: Code,
    description: "Open-source codebase for the entire Surf Health project, including backend, web, and mobile clients.",
    href: "https://github.com/kylechoi101/surf-health",
    external: true
  },
  {
    type: "Research",
    title: "Risk Calibration",
    icon: LineChart,
    description: "Our approach to probability clamping and exceedance risk bands mapping.",
    href: "/research/calibration",
    external: false
  },
  {
    type: "Research",
    title: "Data Sources",
    icon: FileText,
    description: "Overview of hydrologic and environmental data ingested from CDIP, USGS, and CEDEN.",
    href: "/research/sources",
    external: false
  },
  {
    type: "Research",
    title: "Reference: Searcy & Boehm (2021)",
    icon: FileText,
    description: "The 'Mona' reference paper cited by our methodology for marine-micro feature engineering.",
    href: "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8186178/",
    external: true
  },
  {
    type: "Research",
    title: "Driver Labels",
    icon: ShieldCheck,
    description: "Explanations of key factors influencing high-risk and low-risk forecasts.",
    href: "/research/labels",
    external: false
  },
];

const typeColors: Record<string, string> = {
  Documentation: "bg-emerald-50 text-emerald-700",
  API: "bg-amber-50 text-amber-700",
  Codebase: "bg-slate-100 text-slate-700",
  Research: "bg-primary/10 text-primary",
};

export function ArtifactsSection() {
  return (
    <section id="artifacts" className="py-24 bg-background relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6 mb-12">
          <div className="max-w-2xl">
            <span className="text-primary text-sm tracking-widest uppercase font-medium">
              Resources
            </span>
            <h2 className="text-3xl md:text-4xl font-light mt-4 mb-4 text-foreground text-balance">
              Research Artifacts &
              <span className="font-semibold"> Datasets</span>
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              Access the underlying methodology, live system metrics, and our open-source codebase.
            </p>
          </div>
          
          <Button variant="outline" className="self-start md:self-auto" asChild>
            <Link href="https://github.com/kylechoi101/surf-health" target="_blank">
              View on GitHub
              <ExternalLink className="w-4 h-4 ml-2" />
            </Link>
          </Button>
        </div>

        {/* Artifacts Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {artifacts.map((artifact, index) => (
            <Card
              key={index}
              className="group bg-card hover:shadow-md border-border/50 transition-all duration-300"
            >
              <CardContent className="p-6">
                <div className="flex justify-between items-start mb-4">
                  <span className={`inline-block px-3 py-1 rounded text-xs font-medium ${typeColors[artifact.type] || "bg-muted text-muted-foreground"}`}>
                    {artifact.type}
                  </span>
                  <div className="text-muted-foreground group-hover:text-primary transition-colors">
                    <artifact.icon className="w-5 h-5" />
                  </div>
                </div>
                
                {/* Title */}
                <h3 className="text-base font-medium mb-3 text-card-foreground leading-snug">
                  {artifact.title}
                </h3>
                
                {/* Description */}
                <p className="text-muted-foreground text-sm leading-relaxed mb-6">
                  {artifact.description}
                </p>
                
                {/* Actions */}
                <div className="pt-4 border-t border-border/50">
                  <Button variant="ghost" size="sm" className="text-primary hover:text-primary/80 -ml-3" asChild>
                    <Link href={artifact.href} target={artifact.external ? "_blank" : "_self"}>
                      {artifact.external ? <ExternalLink className="w-4 h-4 mr-2" /> : <FileText className="w-4 h-4 mr-2" />}
                      {artifact.external ? "External Link" : "Read More"}
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
