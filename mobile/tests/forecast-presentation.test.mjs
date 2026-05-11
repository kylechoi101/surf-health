import assert from "node:assert/strict";
import test from "node:test";

import {
  advisoryProbabilityPresentation,
  forecastDisplayCopy,
} from "../lib/forecastPresentation.ts";

test("mobile official advisory copy does not call the override modeled risk", () => {
  const forecast = {
    risk_band: "Very High",
    model_risk_band: "Low",
    p_exceed: 0.3,
    p_exceed_raw: 0.08,
    official_advisory_active: true,
    advisory_floor_applied: true,
  };

  assert.equal(forecastDisplayCopy(forecast, "Very High").eyebrow, "Official advisory status");
  assert.equal(forecastDisplayCopy(forecast, "Very High").headline, "Official advisory active.");
  assert.equal(advisoryProbabilityPresentation(forecast).secondaryPercent, 8);
});

test("mobile advisory floor copy explains adjusted display probability", () => {
  const forecast = {
    risk_band: "High",
    model_risk_band: "Low",
    p_exceed: 0.3,
    p_exceed_raw: 0.12,
    advisory_floor_applied: true,
  };

  const copy = forecastDisplayCopy(forecast, "High");
  assert.equal(copy.eyebrow, "Advisory-adjusted risk");
  assert.match(copy.body, /model-only estimate/i);
});
