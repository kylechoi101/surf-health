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
  const id = `bg-${seed}`;
  const s = seed % 4;
  return (
    <svg viewBox="0 0 200 100" preserveAspectRatio="xMidYMid slice"
      style={{ width: "100%", height: "100%", display: "block", ...style }}>
      <defs>
        <linearGradient id={id} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={a}/>
          <stop offset="60%" stopColor={b}/>
          <stop offset="100%" stopColor={c}/>
        </linearGradient>
      </defs>
      <rect width="200" height="100" fill={`url(#${id})`}/>
      <circle cx={160 + s * 5} cy={22} r="10" fill="#fff" opacity="0.35"/>
      <path d={`M0 ${70 + s} C 40 ${62 + s}, 80 ${78 - s}, 120 ${70 + s} S 180 ${66 + s}, 220 ${72}`}
        stroke="#fff" strokeWidth="1.2" fill="none" opacity="0.5"/>
      <path d={`M0 82 C 40 76, 80 88, 120 82 S 180 78, 220 84`}
        stroke="#fff" strokeWidth="1" fill="none" opacity="0.35"/>
      <path d={`M0 100 L0 92 C 40 88, 80 96, 120 92 S 180 88, 220 94 L220 100 Z`}
        fill="#f5e6b8" opacity="0.7"/>
    </svg>
  );
}
