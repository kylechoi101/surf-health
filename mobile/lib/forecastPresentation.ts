type RiskBand = "Low" | "Moderate" | "High" | "Very High";

type ForecastLike = {
  p_exceed?: number | null;
  p_exceed_raw?: number | null;
  official_advisory_active?: boolean;
  advisory_floor_applied?: boolean;
};

const RISK_HEAD: Record<RiskBand, string> = {
  Low: "Low modeled risk.",
  Moderate: "Moderate modeled risk.",
  High: "Elevated modeled risk.",
  "Very High": "Very high modeled risk.",
};

const RISK_BODY: Record<RiskBand, string> = {
  Low: "Model estimates bacteria below the EPA single-sample threshold.",
  Moderate: "Elevated modeled bacterial signal — consider limiting water contact.",
  High: "Model estimates bacteria at or above the EPA threshold. Check county advisories.",
  "Very High": "Model estimates closure-level concentrations. Check the posted county advisory.",
};

function percent(value: number | null | undefined): number | null {
  return value == null ? null : Math.round(value * 100);
}

export function isAdvisoryAdjusted(forecast: Partial<ForecastLike> | null | undefined): boolean {
  return Boolean(forecast?.official_advisory_active || forecast?.advisory_floor_applied);
}

export function advisoryProbabilityPresentation(forecast: Partial<ForecastLike> | null | undefined) {
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

export function forecastDisplayCopy(
  forecast: Partial<ForecastLike> | null | undefined,
  band: RiskBand,
) {
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

  return {
    eyebrow: "Today's modeled risk",
    headline: RISK_HEAD[band],
    body: RISK_BODY[band],
  };
}
