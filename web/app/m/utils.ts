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
    Low: "Low modeled risk.",
    Moderate: "Moderate modeled risk.",
    High: "Elevated modeled risk.",
    "Very High": "Very high modeled risk.",
  };
  return map[band] ?? "Unknown.";
}

export function riskAdvice(band: RiskBand | string): string {
  const map: Record<string, string> = {
    Low: "Model estimates bacteria below the EPA single-sample threshold for marine recreational water.",
    Moderate: "Elevated modeled bacterial signal — consider limiting water contact.",
    High: "Model estimates bacteria at or above the EPA threshold. Check county advisories.",
    "Very High": "Model estimates closure-level concentrations. Check the posted county advisory.",
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
    "San Diego": "Southern California",
    "Los Angeles": "Southern California",
    "Santa Ana": "Southern California",
    "Central Coast": "Central California",
    "San Francisco Bay": "Northern California",
    "North Coast": "Northern California",
    SoCal: "Southern California",
    Central: "Central California",
    NorCal: "Northern California",
  };
  return map[region] ?? region;
}

export function getRegionGroup(region: string): string {
  const dataToGroup: Record<string, string> = {
    "San Diego": "SoCal",
    "Los Angeles": "SoCal",
    "Santa Ana": "SoCal",
    "Central Coast": "Central",
    "San Francisco Bay": "NorCal",
    "North Coast": "NorCal",
  };
  return dataToGroup[region] ?? "Other";
}
