export type RiskBand = "Low" | "Moderate" | "High" | "Very High";

export const RISK_ORDER: readonly RiskBand[] = ["Low", "Moderate", "High", "Very High"];

export const RISK_COPY: Record<RiskBand, { head: string; sub: string; cfu: string; drops: number }> = {
  Low: {
    head: "Low modeled risk.",
    sub: "Lower modeled exceedance risk today.",
    cfu: "< 35 CFU/100mL",
    drops: 1,
  },
  Moderate: {
    head: "Moderate modeled risk.",
    sub: "Elevated modeled risk today.",
    cfu: "35–104",
    drops: 2,
  },
  High: {
    head: "Elevated modeled risk.",
    sub: "High modeled exceedance risk — check county advisories.",
    cfu: "104–320",
    drops: 3,
  },
  "Very High": {
    head: "Very high modeled risk.",
    sub: "Check posted county advisory before entering.",
    cfu: "> 320",
    drops: 3,
  },
};

export const RISK_TOKEN: Record<
  RiskBand,
  {
    c: string;
    bg: string;
    ink: string;
    bgClass: string;
    borderClass: string;
    textClass: string;
  }
> = {
  Low: {
    c: "var(--sl-risk-low)",
    bg: "var(--sl-risk-low-bg)",
    ink: "var(--sl-risk-low-ink)",
    bgClass: "bg-[var(--sl-risk-low-bg)]",
    borderClass: "border-[var(--sl-risk-low)]",
    textClass: "text-[var(--sl-risk-low-ink)]",
  },
  Moderate: {
    c: "var(--sl-risk-mod)",
    bg: "var(--sl-risk-mod-bg)",
    ink: "var(--sl-risk-mod-ink)",
    bgClass: "bg-[var(--sl-risk-mod-bg)]",
    borderClass: "border-[var(--sl-risk-mod)]",
    textClass: "text-[var(--sl-risk-mod-ink)]",
  },
  High: {
    c: "var(--sl-risk-high)",
    bg: "var(--sl-risk-high-bg)",
    ink: "var(--sl-risk-high-ink)",
    bgClass: "bg-[var(--sl-risk-high-bg)]",
    borderClass: "border-[var(--sl-risk-high)]",
    textClass: "text-[var(--sl-risk-high-ink)]",
  },
  "Very High": {
    c: "var(--sl-risk-vh)",
    bg: "var(--sl-risk-vh-bg)",
    ink: "var(--sl-risk-vh-ink)",
    bgClass: "bg-[var(--sl-risk-vh-bg)]",
    borderClass: "border-[var(--sl-risk-vh)]",
    textClass: "text-[var(--sl-risk-vh-ink)]",
  },
};
