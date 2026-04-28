export type RiskBand = "Low" | "Moderate" | "High" | "Very High";

export const RISK_ORDER: readonly RiskBand[] = ["Low", "Moderate", "High", "Very High"];

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
