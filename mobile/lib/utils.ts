import type { RiskBand } from "./api";

export function riskVerdict(band: RiskBand | string): string {
  const m: Record<string, string> = { Low: "Below standard.", Moderate: "Caution.", High: "Avoid.", "Very High": "Stay out." };
  return m[band] ?? "Unknown.";
}

export function riskHead(band: RiskBand | string): string {
  const m: Record<string, string> = { Low: "Below standard.", Moderate: "Caution.", High: "Warning.", "Very High": "Closure level." };
  return m[band] ?? "";
}

export function riskAdvice(band: RiskBand | string): string {
  const m: Record<string, string> = {
    Low: "Conditions favor swimming.",
    Moderate: "Avoid swallowing water.",
    High: "Avoid water contact.",
    "Very High": "Check posted county advisory.",
  };
  return m[band] ?? "";
}

export const RISK_COLORS: Record<string, { bg: string; text: string; deep: string; hero: [string, string] }> = {
  Low:        { bg: "#d8efe4", text: "#175d43", deep: "#2b9e79", hero: ["#2b9e79", "#175d43"] },
  Moderate:   { bg: "#f3e6c1", text: "#6d4a05", deep: "#c99b2d", hero: ["#c99b2d", "#6d4a05"] },
  High:       { bg: "#f2d9ca", text: "#7a2d15", deep: "#c7552e", hero: ["#c7552e", "#7a2d15"] },
  "Very High":{ bg: "#ecc9c1", text: "#561611", deep: "#8a2a20", hero: ["#8a2a20", "#561611"] },
};

export function mToFt(m: number | null | undefined): string {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

export function cToF(c: number | null | undefined): string {
  if (c == null) return "—";
  return Math.round(c * 9 / 5 + 32) + "°F";
}

export function mpsToMph(mps: number | null | undefined): string {
  if (mps == null) return "—";
  return Math.round(mps * 2.237) + " mph";
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
  return Math.round(s) + "s";
}

export function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  return Math.round((Date.now() - new Date(iso).getTime()) / 86400000);
}
