import { MetadataRoute } from "next";
import { listBeaches } from "@/lib/curated";

export const dynamic = "force-static";

const BASE = "https://kylechoi101.github.io/surf-health";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const date = new Date().toISOString();
  const beaches = listBeaches();
  const beachUrls: MetadataRoute.Sitemap = beaches.flatMap((beach) => [
    { url: `${BASE}/beaches/${beach.id}`, lastModified: date, changeFrequency: "daily" as const, priority: 0.6 },
    { url: `${BASE}/b/${beach.id}`, lastModified: date, changeFrequency: "daily" as const, priority: 0.5 },
  ]);

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: BASE, lastModified: new Date(), changeFrequency: "daily", priority: 1.0 },
    { url: `${BASE}/beaches`, lastModified: new Date(), changeFrequency: "daily", priority: 0.9 },
    { url: `${BASE}/methodology`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.7 },
    { url: `${BASE}/research`, lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE}/b`, lastModified: new Date(), changeFrequency: "daily", priority: 0.6 },
  ];

  return [...staticRoutes, ...beachUrls];
}
