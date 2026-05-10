"use client";

import React from "react";
import { RiskBand, RISK_ORDER, RISK_COPY, RISK_TOKEN } from "@/lib/riskData";

export type { RiskBand };
export { RISK_ORDER, RISK_COPY, RISK_TOKEN };

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

/** Renders a compact "Beta forecast" pill when the forecast is a beta model estimate. */
export function BetaNotice({
  isBeta,
  className = "",
}: {
  isBeta?: boolean;
  className?: string;
}) {
  if (!isBeta) return null;
  return (
    <span
      className={`sl-label inline-flex items-center gap-1 rounded-full border border-blue-300/50 bg-blue-50 px-2.5 py-1 text-blue-700 ${className}`}
    >
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <circle cx="5" cy="5" r="4" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <text x="5" y="7.5" textAnchor="middle" fontSize="6" fill="currentColor" fontWeight="700">β</text>
      </svg>
      Beta forecast
    </span>
  );
}

/** Renders a sample-age context badge showing how stale the underlying data is. */
export function RecencyBadge({
  sampleAgeDays,
  recencyBand,
  className = "",
}: {
  sampleAgeDays?: number | null;
  recencyBand?: string;
  className?: string;
}) {
  if (sampleAgeDays == null && !recencyBand) return null;
  const isStale = recencyBand === "stale" || recencyBand === "very_stale";
  const label =
    sampleAgeDays != null
      ? sampleAgeDays === 0
        ? "Sampled today"
        : sampleAgeDays === 1
          ? "Sampled yesterday"
          : `Sampled ${sampleAgeDays}d ago`
      : recencyBand
        ? `Sample: ${recencyBand.replace("_", " ")}`
        : null;
  if (!label) return null;
  return (
    <span
      className={`sl-label inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs ${
        isStale
          ? "border-amber-400/50 bg-amber-50 text-amber-700"
          : "border-[var(--sl-line)] bg-[var(--sl-ecru-deep)] text-[var(--sl-muted)]"
      } ${className}`}
    >
      {label}
    </span>
  );
}
