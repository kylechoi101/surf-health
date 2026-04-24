import { RiskBand } from "@/lib/api";

const toneByBand: Record<RiskBand, string> = {
  Low: "low",
  Moderate: "moderate",
  High: "high",
  "Very High": "very-high"
};

export function RiskBadge({ band }: { band: RiskBand }) {
  return <span className={`risk-badge ${toneByBand[band]}`}>{band}</span>;
}

