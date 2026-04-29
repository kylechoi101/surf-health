"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { 
  Microscope, 
  FlaskConical, 
  Dna,
  Activity,
  Droplets,
  AlertTriangle
} from "lucide-react";

const researchAreas = [
  {
    icon: Microscope,
    title: "Fecal Indicator Bacteria",
    description: "Monitor Enterococcus levels to assess fecal contamination and public health risks.",
    status: "Active",
    link: "/research",
  },
  {
    icon: FlaskConical,
    title: "Harmful Algal Blooms",
    description: "Track cyanobacteria and dinoflagellate populations that produce toxins affecting marine life.",
    status: "Planned",
  },
  {
    icon: Dna,
    title: "Microbial Diversity",
    description: "Study bacterial community composition and its response to environmental stressors.",
    status: "Planned",
  },
  {
    icon: Activity,
    title: "Pathogen Detection",
    description: "Identify waterborne pathogens including Vibrio species and antibiotic-resistant bacteria.",
    status: "Planned",
  },
  {
    icon: Droplets,
    title: "Source Tracking",
    description: "Use molecular methods to determine contamination sources: human, animal, or environmental.",
    status: "Planned",
  },
  {
    icon: AlertTriangle,
    title: "Health Risk Assessment",
    description: "Quantitative microbial risk assessment for recreational water exposure.",
    status: "Planned",
  },
];

export function ResearchSection() {
  return (
    <section id="research" className="py-24 bg-muted/30 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-2xl mb-16">
          <span className="text-primary text-sm tracking-widest uppercase font-medium">
            Research Focus
          </span>
          <h2 className="text-3xl md:text-4xl font-light mt-4 mb-6 text-foreground text-balance">
            Coastal Microbiology
            <span className="font-semibold"> Research Roadmap</span>
          </h2>
          <p className="text-muted-foreground leading-relaxed">
            Our platform supports comprehensive microbial water quality research, providing tools 
            and data for scientists studying bacterial indicators and pathogens in California coastal waters.
          </p>
        </div>

        {/* Research Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {researchAreas.map((area) => (
            <Card
              key={area.title}
              className="group bg-card hover:bg-background border-border/50 transition-all duration-300 relative overflow-hidden"
            >
              {area.link && (
                <Link href={area.link} className="absolute inset-0 z-10" aria-label={area.title} />
              )}
              <CardContent className="p-8">
                <div className="flex justify-between items-start mb-6">
                  <div className="w-12 h-12 rounded-sm bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                    <area.icon className="w-6 h-6 text-primary" />
                  </div>
                  <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded ${
                    area.status === "Active" 
                      ? "bg-emerald-500/10 text-emerald-600" 
                      : "bg-muted text-muted-foreground"
                  }`}>
                    {area.status}
                  </span>
                </div>
                <h3 className="text-lg font-medium mb-3 text-card-foreground">
                  {area.title}
                </h3>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {area.description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
