"use client";

import React from "react";

export const RISK_ORDER = ["Low", "Moderate", "High", "Very High"] as const;
export type RiskBand = (typeof RISK_ORDER)[number];

export const RISK_COPY: Record<RiskBand, { head: string; sub: string; cfu: string; drops: number }> = {
  Low: {
    head: "Below standard.",
    sub: "Conditions favor swimming.",
    cfu: "< 35 CFU/100mL",
    drops: 1,
  },
  Moderate: {
    head: "Caution.",
    sub: "Avoid swallowing water.",
    cfu: "35–104",
    drops: 2,
  },
  High: {
    head: "Warning.",
    sub: "Avoid water contact.",
    cfu: "104–320",
    drops: 3,
  },
  "Very High": {
    head: "Closure level.",
    sub: "Check posted county advisory.",
    cfu: "> 320",
    drops: 3,
  },
};

export const RISK_TOKEN: Record<RiskBand, { c: string; bg: string; ink: string }> = {
  Low: {
    c: "var(--sl-risk-low)",
    bg: "var(--sl-risk-low-bg)",
    ink: "var(--sl-risk-low-ink)",
  },
  Moderate: {
    c: "var(--sl-risk-mod)",
    bg: "var(--sl-risk-mod-bg)",
    ink: "var(--sl-risk-mod-ink)",
  },
  High: {
    c: "var(--sl-risk-high)",
    bg: "var(--sl-risk-high-bg)",
    ink: "var(--sl-risk-high-ink)",
  },
  "Very High": {
    c: "var(--sl-risk-vh)",
    bg: "var(--sl-risk-vh-bg)",
    ink: "var(--sl-risk-vh-ink)",
  },
};

export function DropRow({ band, size = 14 }: { band: RiskBand; size?: number }) {
  const d = RISK_COPY[band].drops;
  const color = RISK_TOKEN[band].c;
  const vh = band === "Very High";
  
  return (
    <span className="inline-flex items-center gap-1">
      {[0, 1, 2].map((i) => {
        const filled = i < d || vh;
        return (
          <svg
            key={i}
            width={size}
            height={size * 1.2}
            viewBox="0 0 12 14"
            aria-hidden="true"
          >
            <path
              d="M6 1 C6 1 1.5 6 1.5 9 A4.5 4.5 0 0 0 10.5 9 C10.5 6 6 1 6 1 Z"
              fill={filled ? color : "none"}
              stroke={color}
              strokeWidth="1.1"
              opacity={filled ? 1 : 0.3}
            />
            {vh && i === 2 && (
              <path
                d="M6 5 V8 M6 10 V10.5"
                stroke="#fff"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
            )}
          </svg>
        );
      })}
    </span>
  );
}

export function SeverityBar({
  band,
  className = "",
  width,
  height,
}: {
  band: RiskBand;
  className?: string;
  width?: string | number;
  height?: number;
}) {
  const idx = RISK_ORDER.indexOf(band);
  return (
    <div
      className={`flex gap-1 ${className}`}
      style={width != null ? { width } : undefined}
      aria-label={`${idx + 1} of 4 — ${band}`}
    >
      {RISK_ORDER.map((b, i) => {
        const on = i <= idx;
        const c = RISK_TOKEN[b].c;
        return (
          <div
            key={b}
            className="flex-1 rounded-[2px]"
            style={{
              height: height ?? 6,
              background: on ? c : "var(--sl-line-soft)",
              opacity: on ? (i === idx ? 1 : 0.55) : 1,
            }}
          />
        );
      })}
    </div>
  );
}

export function RiskChip({
  band,
  ageHours,
  className = "",
}: {
  band: RiskBand;
  ageHours?: number;
  className?: string;
}) {
  const tok = RISK_TOKEN[band];
  return (
    <span
      className={`sl-label inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border ${className}`}
      style={{
        background: tok.bg,
        color: tok.ink,
        borderColor: tok.c,
      }}
    >
      <DropRow band={band} size={10} />
      <span>
        {band}
        {ageHours !== undefined && ageHours > 24
          ? ` · ${Math.floor(ageHours / 24)}d`
          : ""}
      </span>
    </span>
  );
}
