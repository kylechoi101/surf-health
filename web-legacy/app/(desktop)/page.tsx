import React from "react";
import { ShorelifeHero } from "@/components/ShorelifeHero";
import { ShorelifeForecast } from "@/components/ShorelifeForecast";
import { ShorelifeMap } from "@/components/ShorelifeMap";
import { ShorelifeResearch } from "@/components/ShorelifeResearch";
import { ShorelifeArtifacts } from "@/components/ShorelifeArtifacts";
import { ShorelifeFooter } from "@/components/ShorelifeFooter";

export const metadata = {
  title: "Shorelife | Know before you paddle out.",
  description: "Real-time water quality forecasting for the California coast. 300+ stations monitored hourly for bacterial risk.",
};

export default function HomePage() {
  return (
    <main className="min-h-screen">
      {/* Hero Section - The Big Hook */}
      <ShorelifeHero />
      
      {/* Forecast Section - Rapid Digest */}
      <ShorelifeForecast />
      
      {/* Map Section - The Brand Differentiator */}
      <ShorelifeMap />
      
      {/* Research Section - Credibility & Traceability */}
      <ShorelifeResearch />
      
      {/* Artifacts Section - Data Access */}
      <ShorelifeArtifacts />
      
      {/* Footer - The Navigation Hub */}
      <ShorelifeFooter />
    </main>
  );
}
