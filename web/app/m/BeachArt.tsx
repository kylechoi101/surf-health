import type { RiskBand } from "@/lib/api";

const GRADS: Record<string, [string, string, string]> = {
  Low:        ["#60a5fa", "#22c55e", "#fef3c7"],
  Moderate:   ["#f59e0b", "#fbbf24", "#fef3c7"],
  High:       ["#fb923c", "#ef4444", "#fde68a"],
  "Very High": ["#991b1b", "#ef4444", "#fbbf24"],
};

export default function BeachArt({ band, seed = 0, style }: {
  band: RiskBand | string;
  seed?: number;
  style?: React.CSSProperties;
}) {
  const [a, b, c] = GRADS[band] ?? GRADS.Low;
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: `linear-gradient(to bottom, ${a} 0%, ${b} 60%, ${c} 100%)`,
        ...style
      }}
    />
  );
}
