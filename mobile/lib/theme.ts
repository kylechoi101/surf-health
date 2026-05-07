// Single source of truth for visual identity across all screens.
// Mirrors the web --sl-* CSS custom properties so the apps read as one product.

import type { RiskBand } from "./api";

export const palette = {
  navy: "#0b4266",
  navyInk: "#072f49",
  navyDeep: "#062236",
  bone: "#faf6ee",
  ecru: "#f1ead9",
  ecruDeep: "#e8dfcc",
  sand: "#d6cbb1",
  ink: "#1a2730",
  inkSoft: "#3a4750",
  muted: "#5e6b73",
  line: "#d6cbb1",
  lineSoft: "#e8dfcc",
  sun: "#e8b341",
  sunDeep: "#a87f1a",

  white: "#ffffff",
  shadow: "#000000",
} as const;

export const risk: Record<
  RiskBand | string,
  { bg: string; ink: string; deep: string; hero: [string, string]; soft: string }
> = {
  Low: {
    bg: "#d8efe4",
    ink: "#175d43",
    deep: "#2b9e79",
    hero: ["#2b9e79", "#175d43"],
    soft: "#eaf5ee",
  },
  Moderate: {
    bg: "#f3e6c1",
    ink: "#6d4a05",
    deep: "#c99b2d",
    hero: ["#c99b2d", "#6d4a05"],
    soft: "#fbf3dc",
  },
  High: {
    bg: "#f2d9ca",
    ink: "#7a2d15",
    deep: "#c7552e",
    hero: ["#c7552e", "#7a2d15"],
    soft: "#fbe6d9",
  },
  "Very High": {
    bg: "#ecc9c1",
    ink: "#561611",
    deep: "#8a2a20",
    hero: ["#8a2a20", "#561611"],
    soft: "#f6dad3",
  },
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 28,
} as const;

export const typography = {
  // Display copy (verdicts, big numbers): tight + heavy
  display: {
    fontSize: 44,
    fontWeight: "700" as const,
    lineHeight: 48,
    letterSpacing: -0.5,
  },
  title: {
    fontSize: 24,
    fontWeight: "700" as const,
    lineHeight: 30,
    letterSpacing: -0.2,
  },
  body: {
    fontSize: 14,
    fontWeight: "500" as const,
    lineHeight: 20,
    letterSpacing: 0,
  },
  caption: {
    fontSize: 12,
    fontWeight: "500" as const,
    lineHeight: 17,
    letterSpacing: 0,
  },
  // 'Eyebrow' = small uppercase label (used for section headers)
  eyebrow: {
    fontSize: 10,
    fontWeight: "700" as const,
    letterSpacing: 1.4,
    textTransform: "uppercase" as const,
  },
} as const;

export const shadows = {
  card: {
    shadowColor: palette.shadow,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 18,
    elevation: 4,
  },
  hero: {
    shadowColor: palette.shadow,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.12,
    shadowRadius: 24,
    elevation: 8,
  },
  sheet: {
    shadowColor: palette.shadow,
    shadowOffset: { width: 0, height: -10 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 6,
  },
} as const;

export function bandHero(band: RiskBand | string | null | undefined) {
  if (!band) return risk.Moderate.hero;
  return risk[band]?.hero ?? risk.Moderate.hero;
}

export function bandColor(band: RiskBand | string | null | undefined): string {
  if (!band) return palette.muted;
  return risk[band]?.deep ?? palette.muted;
}
