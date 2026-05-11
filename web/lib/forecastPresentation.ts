type RiskBand = "Low" | "Moderate" | "High" | "Very High";

const RISK_COPY: Record<RiskBand, { head: string; sub: string }> = {
  Low: {
    head: "Low modeled risk.",
    sub: "Lower modeled exceedance risk today.",
  },
  Moderate: {
    head: "Moderate modeled risk.",
    sub: "Elevated modeled risk today.",
  },
  High: {
    head: "Elevated modeled risk.",
    sub: "High modeled exceedance risk — check county advisories.",
  },
  "Very High": {
    head: "Very high modeled risk.",
    sub: "Check posted county advisory before entering.",
  },
};

type ForecastLike = {
  risk_band?: RiskBand;
  model_risk_band?: RiskBand | null;
  p_exceed?: number | null;
  p_exceed_raw?: number | null;
  official_advisory_active?: boolean;
  advisory_floor_applied?: boolean;
};

function percent(value: number | null | undefined): number | null {
  return value == null ? null : Math.round(value * 100);
}

export function isAdvisoryAdjusted(forecast: ForecastLike | null | undefined): boolean {
  return Boolean(forecast?.official_advisory_active || forecast?.advisory_floor_applied);
}

export function advisoryProbabilityPresentation(forecast: ForecastLike | null | undefined) {
  const servedPercent = percent(forecast?.p_exceed);
  const rawPercent = percent(forecast?.p_exceed_raw ?? forecast?.p_exceed);

  if (!isAdvisoryAdjusted(forecast)) {
    return {
      primaryLabel: "Exceed chance",
      primaryPercent: servedPercent,
      secondaryLabel: null,
      secondaryPercent: null,
    };
  }

  return {
    primaryLabel: "Advisory display",
    primaryPercent: servedPercent,
    secondaryLabel: "Model-only estimate",
    secondaryPercent: rawPercent,
  };
}

export function forecastDisplayCopy(forecast: ForecastLike | null | undefined, band: RiskBand) {
  if (forecast?.official_advisory_active) {
    return {
      eyebrow: "Official advisory status",
      headline: "Official advisory active.",
      body: "Follow posted county guidance. The model-only estimate is shown for context.",
    };
  }

  if (forecast?.advisory_floor_applied) {
    return {
      eyebrow: "Advisory-adjusted risk",
      headline: "Advisory-adjusted risk.",
      body: "Active advisory context raises the displayed risk. The model-only estimate is shown for context.",
    };
  }

  const copy = RISK_COPY[band] ?? RISK_COPY.Moderate;
  return {
    eyebrow: "Beta forecast",
    headline: copy.head,
    body: copy.sub,
  };
}
