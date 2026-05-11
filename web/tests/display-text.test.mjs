import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import * as utils from "../lib/utils.ts";

test("cleans escaped apostrophes from beach display names", () => {
  assert.equal(typeof utils.cleanDisplayText, "function");
  assert.equal(utils.cleanDisplayText("Black\\\\\\'s Beach"), "Black's Beach");
  assert.equal(utils.cleanDisplayText("Swami\\'s"), "Swami's");
  assert.equal(utils.cleanDisplayText("Surfer's Point"), "Surfer's Point");
});

test("public beach data does not expose escaped display quotes", () => {
  const files = ["beaches.json", "parent_beaches.json"];
  for (const file of files) {
    const data = JSON.parse(fs.readFileSync(new URL(`../public/data/${file}`, import.meta.url), "utf8"));
    const encoded = JSON.stringify(data);
    assert.equal(/\\+['"]/.test(encoded), false, `${file} contains escaped display quotes`);
  }
});

test("public beach data preserves raw model probability for advisory-adjusted forecasts", () => {
  const beaches = JSON.parse(fs.readFileSync(new URL("../public/data/beaches.json", import.meta.url), "utf8"));
  const adjusted = beaches.find((beach) => beach.forecast?.advisory_floor_applied === true);

  if (!adjusted) {
    return;
  }

  assert.equal(typeof adjusted.forecast.p_exceed_raw, "number");
  assert.ok(adjusted.forecast.p_exceed_raw < adjusted.forecast.p_exceed);
  assert.equal(adjusted.forecast.model_risk_band, "Low");
  assert.equal(adjusted.forecast.official_advisory_active, true);
});
