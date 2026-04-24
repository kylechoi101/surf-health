import type { RiskBand } from "./api";

export function riskVerdict(band: RiskBand | string): string {
  const m: Record<string, string> = { Low: "Yes.", Moderate: "Maybe.", High: "Not ideal.", "Very High": "Avoid." };
  return m[band] ?? "Unknown.";
}

export function riskAdvice(band: RiskBand | string): string {
  const m: Record<string, string> = {
    Low: "Bacteria levels are within safe limits. Enjoy the water.",
    Moderate: "Elevated risk — swim with caution, especially near storm drains.",
    High: "High bacteria likely. Consider staying out of the water today.",
    "Very High": "Active contamination likely. Avoid water contact.",
  };
  return m[band] ?? "";
}

export const RISK_COLORS: Record<string, { bg: string; text: string; deep: string; hero: [string, string] }> = {
  Low:        { bg: "#dcfce7", text: "#15803d", deep: "#15803d", hero: ["#10b981", "#047857"] },
  Moderate:   { bg: "#fef3c7", text: "#b45309", deep: "#b45309", hero: ["#f59e0b", "#b45309"] },
  High:       { bg: "#ffedd5", text: "#c2410c", deep: "#c2410c", hero: ["#fb923c", "#c2410c"] },
  "Very High":{ bg: "#fee2e2", text: "#b91c1c", deep: "#b91c1c", hero: ["#f87171", "#991b1b"] },
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
