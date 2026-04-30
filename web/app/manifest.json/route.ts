import { NextResponse } from "next/server";

import { shorelifeManifest } from "@/lib/manifest";

export const dynamic = "force-static";

export function GET() {
  return NextResponse.json(shorelifeManifest());
}
