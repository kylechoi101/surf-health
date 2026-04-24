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

export interface ForecastRecord {
  beach_id: string;
  forecast_date: string;
  risk_band: RiskBand;
  p_exceed: number;
  predicted_log_enterococcus: number | null;
  top_drivers: string[];
  model_version: string;
  forecast_generated_at: string;
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

export interface ExplanationResponse {
  beach_id: string;
  summary: string;
  used_model: string;
}

// On physical devices/emulators, localhost points to the device — use the LAN IP set in .env
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

export const getBeaches = () => request<BeachSummary[]>("/beaches");
export const getForecast = (id: string, date: string) =>
  request<ForecastRecord>(`/beaches/${id}/forecast?date=${date}`);
export const getExplanation = (id: string, date: string) =>
  request<ExplanationResponse>(`/beaches/${id}/forecast/explain?date=${date}`);
