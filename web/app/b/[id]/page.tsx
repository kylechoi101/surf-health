import { Metadata } from "next";
import { getBeaches, getForecast, preferredForecastDate } from "@/lib/api";
import BeachSharePage from "./BeachSharePage";
import { RISK_COPY } from "@/lib/riskData";

export async function generateStaticParams() {
  try {
    const beaches = await getBeaches({ cache: 'force-cache' });
    return beaches.map((b) => ({
      id: b.id,
    }));
  } catch (err) {
    return [{ id: "_" }];
  }
}

export async function generateMetadata(props: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const params = await props.params;
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

export default async function Page(props: { params: Promise<{ id: string }> }) {
  // Although the client component will handle its own loading, 
  // awaiting here ensures compatibility with Next.js 15 routing.
  await props.params;
  return <BeachSharePage />;
}
