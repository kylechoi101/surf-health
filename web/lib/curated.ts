import fs from "fs";
import path from "path";

import { RiskBand } from "@/lib/riskData";

export interface ForecastData {
  risk_band: RiskBand;
  p_exceed: number | null;
  model_version: string;
  forecast_generated_at: string | null;
  top_drivers: string[];
}

export interface EnvData {
  wave_height_m: number | null;
  dominant_period_s: number | null;
  water_temperature_c: number | null;
  salinity_psu: number | null;
  uv_index: number | null;
  wind_speed_mps: number | null;
  wind_direction_deg: number | null;
}

export interface Beach {
  id: string;
  name: string;
  station_name: string;
  county: string;
  region: string;
  latitude: number;
  longitude: number;
  support_status: "production" | "unsupported" | "beta";
  latest_official_sample_at: string | null;
  forecast: ForecastData | null;
  env: EnvData | null;
}

export interface RegionalSummary {
  region: string;
  monitored_site_count: number;
  modeled_site_count: number;
  avg_water_temp_c: number | null;
  avg_wave_height_m: number | null;
  high_risk_count: number;
}

export interface ParentBeach {
  id: string;
  name: string;
  county: string;
  region: string;
  latitude: number;
  longitude: number;
  station_count: number;
  member_beach_ids: string[];
  latest_official_sample_at: string | null;
}

export interface MapSite extends ParentBeach {
  support_status: "production" | "unsupported" | "beta";
  modeled_member_count: number;
  unsupported_member_count: number;
  forecast: ForecastData | null;
  env: EnvData | null;
  latest_modeled_beach: Beach | null;
}

export interface SiteStats {
  totalStations: number;
  modeledStations: number;
  unsupportedStations: number;
  groupedCoastSites: number;
  latestPublishAt: string | null;
  productionModel: string | null;
}

interface SystemHealthFile {
  pipeline_freshness?: string;
  model_registry?: {
    production_model?: string;
  };
}

const FEATURED_PARENT_IDS = [
  "parent-ca857004",
  "parent-ca643858",
  "parent-ca876094-1",
  "parent-ca000886",
  "parent-ca006650",
  "parent-ca696385",
];

function readJson<T>(filename: string): T {
  const filePath = path.join(process.cwd(), "public", "data", filename);
  const data = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(data) as T;
}

function readSystemHealth(): SystemHealthFile {
  const filePath = path.join(process.cwd(), "..", "data", "curated", "system_health.json");
  try {
    const data = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(data) as SystemHealthFile;
  } catch {
    return {};
  }
}

export function listBeaches(): Beach[] {
  return readJson<Beach[]>("beaches.json");
}

export function regionalSummary(): RegionalSummary[] {
  return readJson<RegionalSummary[]>("regional_summary.json");
}

export function listParentBeaches(): ParentBeach[] {
  return readJson<ParentBeach[]>("parent_beaches.json");
}

export function siteStats(): SiteStats {
  const beaches = listBeaches();
  const parents = listParentBeaches();
  const systemHealth = readSystemHealth();
  const modeledStations = beaches.filter((beach) => beach.support_status === "production").length;

  return {
    totalStations: beaches.length,
    modeledStations,
    unsupportedStations: beaches.length - modeledStations,
    groupedCoastSites: parents.length,
    latestPublishAt: systemHealth.pipeline_freshness ?? null,
    productionModel: systemHealth.model_registry?.production_model ?? null,
  };
}

export function siteForMap(): MapSite[] {
  const beaches = listBeaches();
  const parents = listParentBeaches();
  const beachById = new Map(beaches.map((beach) => [beach.id, beach]));

  return parents.map((parent) => {
    const members = parent.member_beach_ids
      .map((beachId) => beachById.get(beachId))
      .filter((beach): beach is Beach => Boolean(beach));

    const supportedMembers = members
      .filter((member) => member.support_status === "production" && member.forecast)
      .sort((left, right) => {
        const rightP = right.forecast?.p_exceed ?? -1;
        const leftP = left.forecast?.p_exceed ?? -1;
        return rightP - leftP;
      });

    const latestModeledBeach = supportedMembers[0] ?? null;

    return {
      ...parent,
      support_status: latestModeledBeach ? "production" : "unsupported",
      modeled_member_count: supportedMembers.length,
      unsupported_member_count: Math.max(parent.member_beach_ids.length - supportedMembers.length, 0),
      forecast: latestModeledBeach?.forecast ?? null,
      env: latestModeledBeach?.env ?? null,
      latest_modeled_beach: latestModeledBeach,
    };
  });
}

export function featuredMapSite(): MapSite {
  const sites = siteForMap();
  for (const id of FEATURED_PARENT_IDS) {
    const match = sites.find((site) => site.id === id && site.support_status === "production");
    if (match) {
      return match;
    }
  }

  const fallback = sites.find((site) => site.support_status === "production");
  if (!fallback) {
    throw new Error("No modeled map site available for homepage feature.");
  }
  return fallback;
}

export function featuredBeaches(limit = 6): Beach[] {
  const beaches = listBeaches();
  const seen = new Set<string>();
  const picks = beaches
    .filter((beach) => beach.support_status === "production" && beach.forecast)
    .filter((beach) => {
      const key = `${beach.county}::${beach.name}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .sort((left, right) => {
      const rightP = right.forecast?.p_exceed ?? -1;
      const leftP = left.forecast?.p_exceed ?? -1;
      return rightP - leftP;
    });

  return picks.slice(0, limit);
}

export function publicRegions(): RegionalSummary[] {
  return regionalSummary().filter((region) => region.modeled_site_count > 0);
}
