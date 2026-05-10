import { cleanDisplayText } from "@/lib/utils";

export type SupportStatus = "production" | "beta" | "unsupported";
export type RiskBand = "Low" | "Moderate" | "High" | "Very High";

export interface BeachSummary {
  id: string;
  name: string;
  county: string;
  region: string;
  support_status: SupportStatus;
  latest_official_sample_at: string | null;
  geometry: {
    latitude: number;
    longitude: number;
  };
}

export type ForecastLabelMode = "model" | "official_advisory_override" | "derived_persistence" | "unavailable";
export type SampleRecencyBand = "fresh" | "recent" | "stale" | "very_stale" | "unknown";

export interface ForecastRecord {
  beach_id: string;
  forecast_date: string;
  risk_band: RiskBand;
  model_risk_band?: RiskBand;
  p_exceed: number;
  predicted_log_enterococcus: number | null;
  lower_prediction_interval: number | null;
  upper_prediction_interval: number | null;
  prediction_interval_level: number | null;
  top_drivers: string[];
  model_version: string;
  forecast_generated_at: string;
  forecast_age_hours?: number;
  official_advisory_active?: boolean;
  forecast_label_mode?: ForecastLabelMode;
  sample_age_days?: number | null;
  sample_recency_band?: SampleRecencyBand;
  is_beta_forecast?: boolean;
  environmental_summary: {
    wave_height_m: number | null;
    dominant_period_s: number | null;
    water_temperature_c: number | null;
    salinity_psu: number | null;
    uv_index: number | null;
    wind_speed_mps: number | null;
    wind_direction_deg: number | null;
  };
}

export interface ObservationResponse {
  beach_id: string;
  observations: Array<{
    sample_time: string;
    analyte: string;
    method: string;
    units: string;
    value: number;
    exceeds_stv: boolean;
  }>;
  advisories: Array<{
    advisory_type: string;
    started_at: string;
    ended_at: string | null;
    status: string;
  }>;
  recent_environment: Array<Record<string, string | number>>;
}

export interface HealthResponse {
  app_env: string;
  pipeline_freshness: string;
  source_freshness: Record<string, string>;
  model_registry: {
    production_model: string;
    candidate_models: string[];
    research_models?: string[];
    production_metrics?: Record<string, number>;
    validation_metrics?: Record<string, number>;
    spatial_metrics?: Record<string, Record<string, number>>;
    deployment_stage?: string;
    public_release_eligible?: boolean;
    promotion_blockers?: string[];
    promotion_policy?: {
      production_models: string[];
      neural_model_status: string;
      spatial_backtests_present: boolean;
    };
    metrics: Record<string, Record<string, number>>;
  };
}

export interface ExplanationResponse {
  beach_id: string;
  summary: string;
  used_model: string;
}

function apiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      ...init
    });
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`);
    }
    return response.json() as Promise<T>;
  } catch (err) {
    console.warn(`Fetch failed for ${path}`, err);
    throw err;
  }
}

function cleanBeachSummary(beach: BeachSummary): BeachSummary {
  return {
    ...beach,
    name: cleanDisplayText(beach.name),
    county: cleanDisplayText(beach.county),
    region: cleanDisplayText(beach.region),
  };
}

export async function getBeaches(init?: RequestInit) {
  const beaches = await request<BeachSummary[]>("/beaches", init);
  return beaches.map(cleanBeachSummary);
}

export async function getForecast(beachId: string, date: string) {
  return request<ForecastRecord>(`/beaches/${beachId}/forecast?date=${date}`);
}

export async function getObservations(beachId: string) {
  return request<ObservationResponse>(`/beaches/${beachId}/observations`);
}

export async function getExplanation(beachId: string, date: string) {
  return request<ExplanationResponse>(`/beaches/${beachId}/forecast/explain?date=${date}`);
}

export async function getSystemHealth() {
  return request<HealthResponse>("/system/health");
}

export function preferredForecastDate() {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  });
  const parts = formatter.formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
