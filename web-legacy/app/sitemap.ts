import { MetadataRoute } from "next";
import { getBeaches } from "@/lib/api";

export const dynamic = "force-static";

const BASE = "https://kylechoi101.github.io/surf-health";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const beaches = await getBeaches({ cache: "force-cache" });

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: BASE, lastModified: new Date(), changeFrequency: "daily", priority: 1.0 },
    { url: `${BASE}/beaches`, lastModified: new Date(), changeFrequency: "daily", priority: 0.9 },
    { url: `${BASE}/methodology`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.7 },
    { url: `${BASE}/research`, lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE}/b`, lastModified: new Date(), changeFrequency: "daily", priority: 0.6 },
  ];

  const beachRoutes: MetadataRoute.Sitemap = beaches.flatMap((b) => [
    { url: `${BASE}/beaches/${b.id}`, lastModified: new Date(), changeFrequency: "daily" as const, priority: 0.6 },
    { url: `${BASE}/b/${b.id}`, lastModified: new Date(), changeFrequency: "daily" as const, priority: 0.5 },
  ]);

  return [...staticRoutes, ...beachRoutes];
}
