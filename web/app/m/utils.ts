import type { RiskBand } from "@/lib/api";

export function riskClass(band: RiskBand | string): string {
  const map: Record<string, string> = {
    Low: "risk-low",
    Moderate: "risk-mod",
    High: "risk-high",
    "Very High": "risk-vh",
  };
  return map[band] ?? "risk-mod";
}

export function riskVerdict(band: RiskBand | string): string {
  const map: Record<string, string> = {
    Low: "Yes.",
    Moderate: "Maybe.",
    High: "Not ideal.",
    "Very High": "Avoid.",
  };
  return map[band] ?? "Unknown.";
}

export function riskAdvice(band: RiskBand | string): string {
  const map: Record<string, string> = {
    Low: "Bacteria levels are within safe limits. Enjoy the water.",
    Moderate: "Elevated risk — swim with caution, especially near storm drains.",
    High: "High bacteria likely. Consider staying out of the water today.",
    "Very High": "Active contamination likely. Avoid water contact.",
  };
  return map[band] ?? "";
}

export function mToFt(m: number | null | undefined): string {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + "ft";
}

export function cToF(c: number | null | undefined): string {
  if (c == null) return "—";
  return Math.round(c * 9 / 5 + 32) + "°F";
}

export function mpsToMph(mps: number | null | undefined): string {
  if (mps == null) return "—";
  return Math.round(mps * 2.237) + "mph";
}

export function fmtUv(uv: number | null | undefined): string {
  if (uv == null) return "—";
  return Math.round(uv).toString();
}

export function uvLabel(uv: number | null | undefined): string {
  if (uv == null) return "";
  if (uv >= 11) return "Extreme";
  if (uv >= 8) return "Very high";
  if (uv >= 6) return "High";
  if (uv >= 3) return "Moderate";
  return "Low";
}

export function fmtPeriod(s: number | null | undefined): string {
  if (s == null) return "";
  return Math.round(s) + "s period";
}

export function regionLabel(region: string): string {
  const map: Record<string, string> = {
    SoCal: "Southern California",
    Central: "Central California",
    NorCal: "Northern California",
    "Los Angeles": "Los Angeles County",
    "San Diego": "San Diego County",
  };
  return map[region] ?? region;
}
