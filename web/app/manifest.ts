import type { MetadataRoute } from "next";

import { shorelifeManifest } from "@/lib/manifest";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return shorelifeManifest();
}
