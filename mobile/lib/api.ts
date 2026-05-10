export type RiskBand = "Low" | "Moderate" | "High" | "Very High";

export interface BeachSummary {
  id: string;
  name: string;
  county: string;
  region: string;
  support_status: string;
  latest_official_sample_at: string | null;
  geometry: { latitude: number; longitude: number };
}

export interface ParentBeachSummary {
  id: string;
  name: string;
  county: string;
  region: string;
  support_status: string;
  station_count: number;
  member_beach_ids: string[];
  latest_official_sample_at: string | null;
  geometry: { latitude: number; longitude: number };
  risk_band: RiskBand | null;
  p_exceed: number | null;
  has_active_advisory: boolean;
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
  recent_environment: Array<Record<string, unknown>>;
}

export interface SystemHealthResponse {
  app_env: string;
  pipeline_freshness: string;
  active_advisories_count?: number;
  model_registry?: Record<string, unknown>;
}

export interface ExplanationResponse {
  beach_id: string;
  summary: string;
  used_model: string;
}

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export function todayLA(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric", month: "2-digit", day: "2-digit",
  });
  const parts = fmt.formatToParts(new Date());
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${v.year}-${v.month}-${v.day}`;
}

export const getParentBeaches = () => request<ParentBeachSummary[]>("/parent-beaches");
export const getBeaches = () => request<BeachSummary[]>("/beaches");
export const getSystemHealth = () => request<SystemHealthResponse>("/system/health");
export const getObservations = (id: string) => request<ObservationResponse>(`/beaches/${id}/observations`);
export const getForecast = (id: string, date: string) =>
  request<ForecastRecord>(`/beaches/${id}/forecast?date=${date}`);
export const getExplanation = (id: string, date: string) =>
  request<ExplanationResponse>(`/beaches/${id}/forecast/explain?date=${date}`);
