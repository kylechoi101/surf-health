import type { MetadataRoute } from "next";

import { siteAsset } from "@/lib/site";

export function shorelifeManifest(): MetadataRoute.Manifest {
  return {
    name: "Shorelife",
    short_name: "Shorelife",
    description: "California beach health forecasts",
    start_url: siteAsset("/"),
    display: "standalone",
    background_color: "#faf6ee",
    theme_color: "#0b4266",
    icons: [
      {
        src: siteAsset("/icon.svg"),
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: siteAsset("/icon.svg"),
        sizes: "192x192",
        type: "image/svg+xml",
        purpose: "maskable",
      },
      {
        src: siteAsset("/icon.svg"),
        sizes: "512x512",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
