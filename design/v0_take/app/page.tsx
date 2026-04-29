import { Header } from "@/components/header";
import { HeroSection } from "@/components/hero-section";
import { ForecastSection } from "@/components/forecast-section";
import { MapSection } from "@/components/map-section";
import { ResearchSection } from "@/components/research-section";
import { ArtifactsSection } from "@/components/artifacts-section";
import { Footer } from "@/components/footer";

export default function HomePage() {
  return (
    <main className="min-h-screen">
      <Header />
      <HeroSection />
      <ForecastSection />
      <MapSection />
      <ResearchSection />
      <ArtifactsSection />
      <Footer />
    </main>
  );
}
