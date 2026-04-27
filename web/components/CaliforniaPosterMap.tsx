import React, { useMemo } from 'react';
import { RiskChip, RISK_TOKEN } from './Risk';

const CA_PATH = `
  M 245 18 L 460 22 L 470 60 L 510 80 L 540 130 L 555 175
  L 565 220 L 568 265 L 555 295 L 540 320 L 522 345 L 505 372
  L 478 408 L 452 445 L 422 488 L 398 522 L 378 552 L 355 588
  L 335 620 L 318 648 L 298 678 L 280 708 L 260 740 L 248 765
  L 240 780 L 80 780 L 60 720 L 50 660 L 45 600 L 50 540
  L 60 480 L 75 420 L 90 360 L 110 300 L 130 240 L 150 180
  L 175 130 L 200 80 L 225 40 Z
`;

const LAT_MIN = 32.4, LAT_MAX = 41.95;
function project(lat: number, lon: number) {
  const y = 22 + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 758;
  const anchors = [
    [41.9, 65], [41.0, 55], [40.0, 60], [39.0, 75], [38.5, 95],
    [38.0, 88], [37.7, 100], [37.0, 130], [36.5, 145], [36.0, 165],
    [35.5, 195], [35.0, 220], [34.5, 245], [34.4, 270], [34.0, 305],
    [33.7, 340], [33.4, 380], [33.0, 415], [32.8, 440], [32.4, 460],
  ];
  let xCoast = 60;
  for (let i = 0; i < anchors.length - 1; i++) {
    if (lat <= anchors[i][0] && lat >= anchors[i+1][0]) {
      const t = (anchors[i][0] - lat) / (anchors[i][0] - anchors[i+1][0]);
      xCoast = anchors[i][1] + t * (anchors[i+1][1] - anchors[i][1]);
      break;
    }
  }
  if (lat > 41.0) xCoast = 60;
  const x = xCoast + 6 + ((lon + 122) * -8);
  return { x, y, xCoast };
}

export function CaliforniaPosterMap({ beaches, activeBeach, onSelect, height = 640 }: any) {
  return (
    <div style={{
      position: 'relative', height, borderRadius: 14, overflow: 'hidden',
      background: 'var(--sl-bone)',
      border: '1px solid var(--sl-line)',
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset',
    }}>
      <svg viewBox="0 0 600 800" preserveAspectRatio="xMidYMid meet"
        width="100%" height="100%" style={{ display: 'block' }}>
        <defs>
          <linearGradient id="ocean" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#dbe9ee"/>
            <stop offset="1" stopColor="#c2d8df"/>
          </linearGradient>
          <linearGradient id="land" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#e9dfc6"/>
            <stop offset="1" stopColor="#dccca5"/>
          </linearGradient>
          <pattern id="topo" x="0" y="0" width="14" height="14" patternUnits="userSpaceOnUse">
            <circle cx="7" cy="7" r="0.6" fill="#bfa97a" opacity="0.45"/>
          </pattern>
          <radialGradient id="sun" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#f5c95e"/>
            <stop offset="0.7" stopColor="#d99a2b"/>
            <stop offset="1" stopColor="#a06a13"/>
          </radialGradient>
        </defs>

        <rect x="0" y="0" width="600" height="800" fill="url(#ocean)"/>

        {[34, 36, 38, 40].map(lat => {
          const y = 22 + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 758;
          return (
            <g key={lat}>
              <line x1="0" y1={y} x2="600" y2={y}
                stroke="#7d95aa" strokeWidth="0.5" strokeDasharray="2 4" opacity="0.45"/>
              <text x="8" y={y - 4} fill="#5e6b73" fontSize="9"
                fontFamily="var(--font-mono)" letterSpacing="0.1em" opacity="0.7">
                {lat}°N
              </text>
            </g>
          );
        })}

        {[120, 200, 320, 440, 580, 700].map((y, i) => (
          <path key={i} d={`M 0 ${y} Q 30 ${y - 3}, 60 ${y} T 120 ${y}`}
            stroke="#a4bdc6" strokeWidth="0.8" fill="none" opacity="0.5"/>
        ))}

        <path d={CA_PATH} fill="url(#land)"/>
        <path d={CA_PATH} fill="url(#topo)" opacity="0.6"/>

        <path d={`
          M 225 40 L 200 80 L 175 130 L 150 180 L 130 240
          L 110 300 L 90 360 L 75 420 L 60 480 L 50 540
          L 45 600 L 50 660 L 60 720 L 80 780
        `} stroke="var(--sl-navy)" strokeWidth="1.2" fill="none" opacity="0.55"/>

        <g transform="translate(490 110)">
          <circle r="56" fill="url(#sun)" opacity="0.9"/>
          {[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map(deg => (
            <line key={deg} x1="62" y1="0" x2="84" y2="0"
              transform={`rotate(${deg})`}
              stroke="#d99a2b" strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
          ))}
        </g>

        <text x="380" y="160" textAnchor="middle"
          fontFamily="var(--font-heading)" fontSize="38" fontWeight="450"
          fill="#8a6e2e" opacity="0.22" letterSpacing="0.18em">
          CALIFORNIA
        </text>
        <text x="380" y="190" textAnchor="middle"
          fontFamily="var(--font-mono)" fontSize="9.5"
          fill="#8a6e2e" opacity="0.42" letterSpacing="0.32em">
          PACIFIC SHORELINE
        </text>

        {[
          { label: 'NORCAL',  x: 95,  y: 270 },
          { label: 'CENTRAL', x: 185, y: 510 },
          { label: 'SOCAL',   x: 365, y: 745 },
        ].map(r => (
          <text key={r.label} x={r.x} y={r.y}
            fontFamily="var(--font-mono)" fontSize="9.5" fill="var(--sl-muted)"
            letterSpacing="0.28em" opacity="0.7">
            {r.label}
          </text>
        ))}

        {beaches.map((b: any) => {
          if (!b.lat || !b.lon) return null;
          const { x, y } = project(b.lat, b.lon);
          const isActive = activeBeach && activeBeach.id === b.id;
          const tok = RISK_TOKEN[b.risk || 'Moderate'];
          const r = isActive ? 6 : 3.5;
          return (
            <g key={b.id} style={{ cursor: 'pointer' }}
               onMouseEnter={() => onSelect && onSelect(b)}>
              {isActive && <circle cx={x} cy={y} r={14} fill={tok.c} opacity="0.18"/>}
              <circle cx={x} cy={y} r={r}
                fill={tok.c}
                stroke="var(--sl-bone)" strokeWidth={isActive ? 2 : 1}/>
            </g>
          );
        })}

        <g transform="translate(540 720)">
          <circle r="22" fill="var(--sl-bone)" stroke="var(--sl-line)"/>
          <path d="M 0 -16 L 4 0 L 0 16 L -4 0 Z" fill="var(--sl-navy)"/>
          <path d="M -16 0 L 0 4 L 16 0 L 0 -4 Z" fill="var(--sl-driftwood)"/>
          <text x="0" y="-26" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9"
            fill="var(--sl-navy)" letterSpacing="0.1em">N</text>
        </g>

        <g transform="translate(45 760)">
          <line x1="0" y1="0" x2="80" y2="0" stroke="var(--sl-navy)" strokeWidth="1.5"/>
          <line x1="0" y1="-3" x2="0" y2="3" stroke="var(--sl-navy)" strokeWidth="1.5"/>
          <line x1="40" y1="-2" x2="40" y2="2" stroke="var(--sl-navy)" strokeWidth="1"/>
          <line x1="80" y1="-3" x2="80" y2="3" stroke="var(--sl-navy)" strokeWidth="1.5"/>
          <text x="0" y="14" fontFamily="var(--font-mono)" fontSize="9"
            fill="var(--sl-muted)" letterSpacing="0.08em">100 MI</text>
        </g>

        {activeBeach && (() => {
          const p = project(activeBeach.lat, activeBeach.lon);
          const cx = Math.min(p.x + 30, 420);
          const cy = Math.max(40, Math.min(p.y - 20, 720));
          return (
            <g>
              <line x1={p.x} y1={p.y} x2={cx} y2={cy + 30}
                stroke="var(--sl-navy)" strokeWidth="1" strokeDasharray="2 2" opacity="0.6"/>
              <foreignObject x={cx} y={cy} width="200" height="86">
                <div style={{
                  background: 'var(--sl-bone)',
                  border: '1px solid var(--sl-line)',
                  borderRadius: 10, padding: '10px 12px',
                  fontFamily: 'var(--font-text)',
                  boxShadow: '0 4px 12px rgba(11,66,102,0.10)',
                }}>
                  <div style={{ color: 'var(--sl-muted)', fontSize: 9, fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                    {activeBeach.county?.toUpperCase()}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--sl-navy)', marginTop: 2 }}>
                    {activeBeach.name}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                    <RiskChip band={activeBeach.risk}/>
                    <span style={{ fontSize: 10, color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)' }}>
                      {activeBeach.waveFt}ft · {activeBeach.temp}°F
                    </span>
                  </div>
                </div>
              </foreignObject>
            </g>
          );
        })()}
      </svg>
    </div>
  );
}
