"use client";

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
    description: "Monitor E. coli and Enterococcus levels to assess fecal contamination and public health risks.",
  },
  {
    icon: FlaskConical,
    title: "Harmful Algal Blooms",
    description: "Track cyanobacteria and dinoflagellate populations that produce toxins affecting marine life.",
  },
  {
    icon: Dna,
    title: "Microbial Diversity",
    description: "Study bacterial community composition and its response to environmental stressors.",
  },
  {
    icon: Activity,
    title: "Pathogen Detection",
    description: "Identify waterborne pathogens including Vibrio species and antibiotic-resistant bacteria.",
  },
  {
    icon: Droplets,
    title: "Source Tracking",
    description: "Use molecular methods to determine contamination sources: human, animal, or environmental.",
  },
  {
    icon: AlertTriangle,
    title: "Health Risk Assessment",
    description: "Quantitative microbial risk assessment for recreational water exposure.",
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
            <span className="font-semibold"> Research Areas</span>
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
              className="group bg-card hover:bg-background border-border/50 transition-all duration-300"
            >
              <CardContent className="p-8">
                <div className="w-12 h-12 rounded-sm bg-primary/10 flex items-center justify-center mb-6 group-hover:bg-primary/20 transition-colors">
                  <area.icon className="w-6 h-6 text-primary" />
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
