import { Metadata } from "next";
import { getBeaches, getForecast, preferredForecastDate } from "@/lib/api";
import BeachSharePage from "./BeachSharePage";
import { RISK_COPY } from "@/components/Risk";

export async function generateStaticParams() {
  const beaches = await getBeaches({ cache: 'force-cache' });
  return beaches.map((b) => ({
    id: b.id,
  }));
}

export async function generateMetadata({ params }: { params: { id: string } }): Promise<Metadata> {
  const id = params.id;
  const date = preferredForecastDate();
  try {
    const [beaches, forecast] = await Promise.all([
      getBeaches({ cache: 'force-cache' }),
      getForecast(id, date).catch(() => null),
    ]);
    const beach = beaches.find(b => b.id === id);
    if (!beach) return { title: "Beach not found · Shorelife" };

    const band = forecast?.risk_band || "Moderate";
    const copy = RISK_COPY[band];

    return {
      title: `${beach.name} · ${copy.head} · Shorelife`,
      description: copy.sub,
      openGraph: {
        title: `${beach.name} · ${copy.head}`,
        description: copy.sub,
        images: [`/og/${beach.id}-${band.toLowerCase().replace(' ', '-')}.png`],
      },
      twitter: {
        card: "summary_large_image",
        title: `${beach.name} · ${copy.head}`,
        description: copy.sub,
      }
    };
  } catch {
    return { title: "Beach Forecast · Shorelife" };
  }
}

export default function Page() {
  return <BeachSharePage />;
}
