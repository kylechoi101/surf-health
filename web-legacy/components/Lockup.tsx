"use client";

import React, { useId } from "react";

// Shorelife mark — disciplined logo for app/header use.
export function ShorelifeMark({
  size = 40,
  ocean = "var(--sl-navy)",
  sand = "var(--sl-sun)", // warm sand-poster mustard reads at small sizes
  coast = "var(--sl-bone)", // negative-space hairline — bright against both fills
  showFrame = false, // off by default; circle is implicit via clipPath
}: {
  size?: number;
  ocean?: string;
  sand?: string;
  coast?: string;
  showFrame?: boolean;
}) {
  const uid = useId();
  const rId = `sl-ring-${uid.replace(/:/g, "")}`;
  
  // Coordinate system: 100×100, centered.
  const SCURVE = "M 50 4 C 12 18 12 38 50 50 C 88 62 88 82 50 96";

  // Filled "ocean" half: everything LEFT of the curve, bounded by the tile.
  const OCEAN = `M 0 0 L 50 0
                 C 12 18 12 38 50 50
                 C 88 62 88 82 50 96
                 L 50 100 L 0 100 Z`;
                 
  // Filled "sand" half: everything RIGHT of the curve.
  const SAND = `M 50 0 L 100 0 L 100 100 L 50 100
                C 88 82 88 62 50 50
                C 12 38 12 18 50 0 Z`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      style={{ display: "block", flexShrink: 0 }}
      shapeRendering="geometricPrecision"
      aria-hidden="true"
    >
      <defs>
        <clipPath id={rId}>
          <circle cx="50" cy="50" r="48" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${rId})`}>
        <path d={OCEAN} fill={ocean} />
        <path d={SAND} fill={sand} />
        <path
          d={SCURVE}
          stroke={coast}
          strokeWidth="2.4"
          fill="none"
          strokeLinecap="round"
        />
      </g>

      {showFrame && (
        <circle
          cx="50"
          cy="50"
          r="48"
          fill="none"
          stroke={ocean}
          strokeWidth="1"
          opacity="0.25"
        />
      )}
    </svg>
  );
}

export function ShorelifeWordmark({
  size = 30,
  ink = "var(--sl-navy)",
}: {
  size?: number;
  ink?: string;
}) {
  return (
    <span
      className="sl-display"
      style={{
        fontSize: size,
        color: ink,
        letterSpacing: "-0.025em",
        lineHeight: 0.9,
      }}
    >
      shorelife
    </span>
  );
}

export function LockupHorizontal({
  size = 32,
  ink = "var(--sl-navy)",
  subtitle,
  className = "",
}: {
  size?: number;
  ink?: string;
  subtitle?: string;
  className?: string;
}) {
  return (
    <div
      className={`inline-flex items-center ${className}`}
      style={{ gap: size * 0.55 }}
    >
      <ShorelifeMark size={size * 1.15} ocean={ink} />
      <div className="flex flex-col gap-0.5">
        <ShorelifeWordmark size={size} ink={ink} />
        {subtitle && (
          <span className="sl-eyebrow" style={{ fontSize: size * 0.3 }}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
