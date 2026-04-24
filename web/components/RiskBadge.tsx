import { RiskBand } from "@/lib/api";

const toneByBand: Record<RiskBand, string> = {
  Low: "low",
  Moderate: "moderate",
  High: "high",
  "Very High": "very-high"
};

export function RiskBadge({ band, ageHours }: { band: RiskBand; ageHours?: number }) {
  return (
    <span className={`risk-badge ${toneByBand[band]}`}>
      {band}
      {ageHours !== undefined && ageHours > 24 && ` (${Math.floor(ageHours / 24)}d old)`}
    </span>
  );
}

