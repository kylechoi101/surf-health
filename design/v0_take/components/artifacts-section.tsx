"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { 
  FileText, 
  Download,
  ExternalLink,
  Calendar,
  User
} from "lucide-react";

const artifacts = [
  {
    type: "Dataset",
    title: "California Beach Bacteria Monitoring 2024-2026",
    author: "CA Water Resources Board",
    date: "April 2026",
    description: "Comprehensive fecal indicator bacteria data from 450+ monitoring stations along California coast.",
    downloads: "3.2K",
  },
  {
    type: "Publication",
    title: "Enterococcus Patterns in Southern California Surf Zones",
    author: "Dr. Emily Rodriguez, UCLA",
    date: "March 2026",
    description: "Peer-reviewed analysis of bacterial contamination patterns and their correlation with stormwater runoff.",
    downloads: "1.4K",
  },
  {
    type: "Protocol",
    title: "qPCR Methods for Rapid Bacteria Detection",
    author: "ShoreLife Research Team",
    date: "February 2026",
    description: "Standardized molecular protocols for rapid quantification of fecal indicator bacteria in recreational waters.",
    downloads: "2.8K",
  },
  {
    type: "Dataset",
    title: "Harmful Algal Bloom Records - Central Coast",
    author: "Monterey Bay Aquarium Research",
    date: "January 2026",
    description: "HAB event documentation including Pseudo-nitzschia and domoic acid concentration data.",
    downloads: "892",
  },
  {
    type: "Report",
    title: "Annual Water Quality Assessment - San Diego",
    author: "San Diego County Health",
    date: "December 2025",
    description: "Comprehensive annual report on beach water quality, advisories, and closure events.",
    downloads: "1.6K",
  },
  {
    type: "Publication",
    title: "Source Tracking of Fecal Contamination Using MST",
    author: "Dr. James Chen, Stanford",
    date: "November 2025",
    description: "Microbial source tracking study identifying human vs. animal contamination sources in Bay Area beaches.",
    downloads: "2.1K",
  },
];

const typeColors: Record<string, string> = {
  Dataset: "bg-emerald-50 text-emerald-700",
  Publication: "bg-primary/10 text-primary",
  Report: "bg-amber-50 text-amber-700",
  Protocol: "bg-slate-100 text-slate-700",
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
              Access peer-reviewed publications, monitoring datasets, and standardized protocols 
              for California coastal microbiology research.
            </p>
          </div>
          
          <Button variant="outline" className="self-start md:self-auto">
            View All Resources
            <ExternalLink className="w-4 h-4 ml-2" />
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
                {/* Type Badge */}
                <span className={`inline-block px-3 py-1 rounded text-xs font-medium mb-4 ${typeColors[artifact.type]}`}>
                  {artifact.type}
                </span>
                
                {/* Title */}
                <h3 className="text-base font-medium mb-3 text-card-foreground leading-snug">
                  {artifact.title}
                </h3>
                
                {/* Description */}
                <p className="text-muted-foreground text-sm leading-relaxed mb-4">
                  {artifact.description}
                </p>
                
                {/* Meta */}
                <div className="flex items-center gap-4 text-xs text-muted-foreground mb-4">
                  <span className="flex items-center gap-1">
                    <User className="w-3 h-3" />
                    {artifact.author}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {artifact.date}
                  </span>
                </div>
                
                {/* Actions */}
                <div className="flex items-center justify-between pt-4 border-t border-border/50">
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Download className="w-3 h-3" />
                    {artifact.downloads} downloads
                  </span>
                  <Button variant="ghost" size="sm" className="text-primary hover:text-primary/80">
                    <FileText className="w-4 h-4 mr-1" />
                    Access
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
