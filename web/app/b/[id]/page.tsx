import { Metadata } from "next";
import BeachSharePage from "./BeachSharePage";
import { listBeaches } from "@/lib/curated";
import { RISK_COPY } from "@/lib/riskData";

const UNSUPPORTED_SHARE_COPY = {
  head: "No model coverage",
  sub: "Showing the latest official sample instead of a calibrated Shorelife forecast.",
};

export async function generateStaticParams() {
  return listBeaches().map((beach) => ({
    id: beach.id,
  }));
}

export async function generateMetadata(props: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const params = await props.params;
  const id = params.id;
  const beach = listBeaches().find((candidate) => candidate.id === id);
  if (!beach) {
    return { title: "Beach not found · Shorelife" };
  }

  const isUnsupported = beach.support_status === "unsupported";
  const band = beach.forecast?.risk_band || "Moderate";
  const copy = isUnsupported
    ? UNSUPPORTED_SHARE_COPY
    : beach.forecast
      ? RISK_COPY[band]
      : {
          head: "Forecast unavailable",
          sub: "Daily Shorelife beach health updates based on official monitoring and coastal conditions.",
        };

  return {
    title: `${beach.name} · ${copy.head} · Shorelife`,
    description: copy.sub,
    alternates: {
      canonical: `/b/${id}`,
    },
    openGraph: {
      title: `${beach.name} · ${copy.head}`,
      description: copy.sub,
      url: `/b/${id}`,
    },
    twitter: {
      card: "summary_large_image",
      title: `${beach.name} · ${copy.head}`,
      description: copy.sub,
    },
  };
}

export default async function Page(props: { params: Promise<{ id: string }> }) {
  // Although the client component will handle its own loading, 
  // awaiting here ensures compatibility with Next.js 15 routing.
  const params = await props.params;
  return <BeachSharePage beachId={params.id} />;
}
