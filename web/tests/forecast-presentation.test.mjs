import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  advisoryProbabilityPresentation,
  forecastDisplayCopy,
} from "../lib/forecastPresentation.ts";

test("official advisory display separates override from model-only probability", () => {
  const forecast = {
    risk_band: "Very High",
    model_risk_band: "Low",
    p_exceed: 0.3,
    p_exceed_raw: 0.08,
    official_advisory_active: true,
    advisory_floor_applied: true,
  };

  assert.deepEqual(advisoryProbabilityPresentation(forecast), {
    primaryLabel: "Advisory display",
    primaryPercent: 30,
    secondaryLabel: "Model-only estimate",
    secondaryPercent: 8,
  });

  assert.equal(forecastDisplayCopy(forecast, "Very High").headline, "Official advisory active.");
  assert.match(forecastDisplayCopy(forecast, "Very High").body, /model-only estimate/i);
});

test("normal model display keeps the single modeled probability", () => {
  const forecast = {
    risk_band: "Moderate",
    p_exceed: 0.18,
    p_exceed_raw: 0.18,
  };

  assert.deepEqual(advisoryProbabilityPresentation(forecast), {
    primaryLabel: "Exceed chance",
    primaryPercent: 18,
    secondaryLabel: null,
    secondaryPercent: null,
  });

  assert.equal(forecastDisplayCopy(forecast, "Moderate").headline, "Moderate modeled risk.");
});

test("share page metadata uses advisory-aware presentation copy", () => {
  const source = fs.readFileSync("app/b/[id]/page.tsx", "utf8");

  assert.match(source, /forecastDisplayCopy/);
  assert.doesNotMatch(source, /RISK_COPY/);
});
