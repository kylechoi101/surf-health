import type { Metadata } from "next";
import { Suspense } from "react";

import SearchParamsSharePage from "./SearchParamsSharePage";

export const metadata: Metadata = {
  title: "Beach share preview · Shorelife",
  description: "Shareable Shorelife beach forecast cards for California beaches.",
  alternates: {
    canonical: "/b/",
  },
  openGraph: {
    title: "Beach share preview · Shorelife",
    description: "Shareable Shorelife beach forecast cards for California beaches.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Beach share preview · Shorelife",
    description: "Shareable Shorelife beach forecast cards for California beaches.",
  },
};

function LoadingState() {
  return (
    <main className="min-h-screen bg-background flex items-center justify-center">
      <div className="text-muted-foreground animate-pulse font-mono text-sm tracking-widest uppercase">
        Loading…
      </div>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<LoadingState />}>
      <SearchParamsSharePage />
    </Suspense>
  );
}
