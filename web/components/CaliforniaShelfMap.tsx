"use client";

import { BeachSummary } from "@/lib/api";
import Link from "next/link";
import { useMemo, useState } from "react";

const LAT_MIN = 32.4;
const LAT_MAX = 41.9;
const LON_MIN = -124.5;
const LON_MAX = -117.0;

function project(latitude: number, longitude: number) {
  const x = ((longitude - LON_MIN) / (LON_MAX - LON_MIN)) * 100;
  const y = 100 - ((latitude - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 100;
  return { x, y };
}

export function CaliforniaShelfMap({ beaches }: { beaches: BeachSummary[] }) {
  const [hovered, setHovered] = useState<string | null>(null);

  const plotted = useMemo(
    () =>
      beaches.map((beach) => ({
        ...beach,
        ...project(beach.geometry.latitude, beach.geometry.longitude)
      })),
    [beaches]
  );

  const active = plotted.find((beach) => beach.id === hovered) ?? plotted[0];

  return (
    <div className="map-shell">
      <div className="map-header">
        <p className="eyebrow">California Marine Stations</p>
        <h3>Statewide nearshore health board</h3>
      </div>
      <div className="map-grid">
        <svg viewBox="0 0 100 100" className="coast-map" aria-label="California beach station map">
          <defs>
            <linearGradient id="swellGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#c5ffec" />
              <stop offset="100%" stopColor="#4dd5a8" />
            </linearGradient>
          </defs>
          <path
            d="M20 7 C24 11, 25 17, 22 25 C21 30, 25 35, 23 40 C20 47, 23 53, 20 61 C18 66, 18 70, 21 76 C24 83, 25 88, 22 94"
            fill="none"
            stroke="url(#swellGradient)"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
          <path
            d="M28 6 C32 15, 29 22, 31 31 C33 38, 35 46, 33 57 C31 67, 34 79, 31 95"
            fill="none"
            stroke="rgba(255,255,255,0.18)"
            strokeWidth="10"
            strokeLinecap="round"
          />
          {plotted.map((beach) => (
            <g key={beach.id}>
              <circle
                cx={beach.x}
                cy={beach.y}
                r={hovered === beach.id ? 2.9 : 2.2}
                className={`map-point ${beach.support_status}`}
                onMouseEnter={() => setHovered(beach.id)}
                onMouseLeave={() => setHovered(null)}
              />
            </g>
          ))}
        </svg>
        <div className="map-callout">
          <p className="map-region">{active.region}</p>
          <h4>{active.name}</h4>
          <p>
            {active.county} County • {active.support_status}
          </p>
          <Link href={`/beaches/${active.id}`} className="pill-link">
            Open forecast
          </Link>
        </div>
      </div>
    </div>
  );
}

