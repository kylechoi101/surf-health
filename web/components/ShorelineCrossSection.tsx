import React from 'react';
import { RISK_TOKEN } from './Risk';

export function ShorelineCrossSection({ band = 'Low', height = 360 }: { band?: string, height?: number }) {
  const W = 1200, H = height;
  const tok = RISK_TOKEN[band] || RISK_TOKEN['Low'];

  const surfaceY = H * 0.30;
  const beachStart = W * 0.62;
  const dryStart   = W * 0.74;
  const seaFloor = (x: number) => {
    if (x <= 0) return surfaceY + H * 0.55;
    if (x >= beachStart) {
      const t = (x - beachStart) / (W - beachStart);
      return surfaceY - t * H * 0.15;
    }
    const t = x / beachStart;
    const depth = H * (0.55 - 0.55 * Math.pow(t, 1.6));
    return surfaceY + depth;
  };

  const floorPts = [];
  for (let x = 0; x <= W; x += 8) floorPts.push([x, seaFloor(x)]);
  const floorPath = floorPts.map((p, i) =>
    (i === 0 ? 'M ' : 'L ') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const seaPath = `${floorPath} L ${W} ${surfaceY} L 0 ${surfaceY} Z`;
  const sandPath = `${floorPath} L ${W} ${H} L 0 ${H} Z`;

  const stations = [
    { id: 'A', x: W * 0.10, label: 'Offshore',     sub: 'buoy 46221' },
    { id: 'B', x: W * 0.34, label: 'Mid-shelf',    sub: 'CDIP nearshore' },
    { id: 'C', x: W * 0.52, label: 'Surf zone',    sub: 'culture sample' },
    { id: 'D', x: W * 0.68, label: 'Swash',        sub: 'tide gauge' },
  ];

  const partCount = { Low: 8, Moderate: 22, High: 50, 'Very High': 90 }[band as any] || 8;

  let wavePath = `M 0 ${surfaceY}`;
  for (let x = 0; x <= W * 0.62; x += 12) {
    const amp = x < W * 0.4 ? 1.2 : 1.8;
    const y = surfaceY + Math.sin(x / 28) * amp;
    wavePath += ` L ${x} ${y.toFixed(1)}`;
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
      preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="cs-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#cdd9de" stopOpacity="0.7"/>
          <stop offset="1" stopColor="#a4b8c2" stopOpacity="0.5"/>
        </linearGradient>
        <pattern id="cs-sand" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="#e9dfc6"/>
          <circle cx="2" cy="2" r="0.45" fill="#bfa97a" opacity="0.55"/>
          <circle cx="5" cy="4" r="0.35" fill="#bfa97a" opacity="0.4"/>
        </pattern>
      </defs>

      <rect x="0" y="0" width={W} height={surfaceY} fill="var(--sl-bone)"/>
      <path d={seaPath} fill="url(#cs-water)"/>
      <path d={sandPath} fill="url(#cs-sand)"/>

      {[1, 2, 3, 4].map(i => {
        const y = surfaceY + (H * 0.55 / 4) * i;
        const depth = i * 5;
        return (
          <g key={i}>
            <line x1="0" y1={y} x2={W} y2={y}
              stroke="#0b4266" strokeWidth="0.35" strokeDasharray="2 4" opacity="0.18"/>
            <text x="14" y={y - 4} fontFamily="var(--font-mono)" fontSize="9"
              fill="var(--sl-muted)" letterSpacing="0.1em">−{depth}m</text>
          </g>
        );
      })}

      <line x1="0" y1={surfaceY} x2={W} y2={surfaceY}
        stroke="var(--sl-navy)" strokeWidth="0.9" opacity="0.55"/>
      <text x={W - 14} y={surfaceY - 6} textAnchor="end"
        fontFamily="var(--font-mono)" fontSize="9" letterSpacing="0.18em"
        fill="var(--sl-navy)" opacity="0.7">
        MEAN SEA LEVEL · 0M
      </text>

      <path d={wavePath} stroke="var(--sl-navy)" strokeWidth="0.7" fill="none" opacity="0.4"/>

      <rect x={W * 0.46} y={surfaceY} width={W * 0.16} height={H * 0.55}
        fill={tok.c} opacity="0.06"/>
      <line x1={W * 0.46} y1={surfaceY - 8} x2={W * 0.46} y2={H - 30}
        stroke={tok.c} strokeWidth="0.5" strokeDasharray="2 3" opacity="0.6"/>
      <line x1={W * 0.62} y1={surfaceY - 8} x2={W * 0.62} y2={H - 30}
        stroke={tok.c} strokeWidth="0.5" strokeDasharray="2 3" opacity="0.6"/>
      <text x={W * 0.54} y={surfaceY - 14} textAnchor="middle"
        fontFamily="var(--font-mono)" fontSize="9" letterSpacing="0.18em"
        fill={tok.c}>SURF ZONE</text>

      <g>
        {[...Array(partCount)].map((_, i) => {
          const seed = (i * 9301 + 49297) % 233280 / 233280;
          const seed2 = (i * 1597 + 51749) % 233280 / 233280;
          const x = W * 0.05 + seed * W * 0.55;
          const yMin = surfaceY + 6;
          const yMax = seaFloor(x) - 4;
          const y = yMin + seed2 * (yMax - yMin);
          if (y >= yMax) return null;
          return <circle key={i} cx={x} cy={y} r={0.9} fill={tok.c} opacity="0.55"/>;
        })}
      </g>

      <path d={floorPath} stroke="var(--sl-navy-ink)" strokeWidth="1.2" fill="none"/>

      <path d={`M ${beachStart} ${surfaceY}
        L ${W} ${seaFloor(W)} L ${W} ${surfaceY} Z`}
        fill="#d9c49a" opacity="0.55"/>

      {stations.map((st) => {
        const x = st.x;
        const yFloor = seaFloor(x);
        const yTop = 22;
        return (
          <g key={st.id}>
            <line x1={x} y1={surfaceY} x2={x} y2={yFloor}
              stroke="var(--sl-navy)" strokeWidth="0.7"
              strokeDasharray="2 3" opacity="0.55"/>
            <line x1={x - 4} y1={surfaceY} x2={x + 4} y2={surfaceY}
              stroke="var(--sl-navy)" strokeWidth="1.1"/>
            <circle cx={x} cy={yFloor} r="3" fill="var(--sl-bone)"
              stroke="var(--sl-navy-ink)" strokeWidth="1"/>
            <line x1={x} y1={yTop + 14} x2={x} y2={surfaceY}
              stroke="var(--sl-muted)" strokeWidth="0.5" opacity="0.7"/>
            <text x={x} y={yTop} textAnchor="middle"
              fontFamily="var(--font-mono)" fontSize="10" fontWeight={500}
              letterSpacing="0.18em" fill="var(--sl-navy-ink)">
              {st.id} · {st.label.toUpperCase()}
            </text>
            <text x={x} y={yTop + 12} textAnchor="middle"
              fontFamily="var(--font-mono)" fontSize="8.5"
              letterSpacing="0.1em" fill="var(--sl-muted)">
              {st.sub}
            </text>
          </g>
        );
      })}

      <g transform={`translate(28 ${H - 36})`}>
        <text fontFamily="var(--font-mono)" fontSize="9" letterSpacing="0.20em"
          fill="var(--sl-muted)">FIG. 02 · SHORELINE PROFILE</text>
        <text y="14" fontFamily="var(--font-heading)" fontSize="14" fontWeight={500}
          fill="var(--sl-navy-ink)">
          What the model "sees" when it forecasts a beach.
        </text>
      </g>

      <g transform={`translate(${W - 160} ${H - 28})`}>
        <line x1="0" y1="0" x2="100" y2="0" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <line x1="0" y1="-3" x2="0" y2="3" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <line x1="50" y1="-2" x2="50" y2="2" stroke="var(--sl-navy-ink)" strokeWidth="1"/>
        <line x1="100" y1="-3" x2="100" y2="3" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <text x="0" y="14" fontFamily="var(--font-mono)" fontSize="9"
          letterSpacing="0.12em" fill="var(--sl-muted)">
          0 ······ 50M ······ 100M (HORIZONTAL, NOT TO SCALE)
        </text>
      </g>
    </svg>
  );
}