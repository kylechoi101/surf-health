import assert from "node:assert/strict";
import test from "node:test";

import {
  filterModeledBeaches,
  findModeledBeach,
  hasModelCoverage,
} from "../lib/coverage.ts";

const modeledBeach = {
  id: "modeled",
  name: "Modeled Beach",
  support_status: "production",
};

const betaBeach = {
  id: "beta",
  name: "Beta Beach",
  support_status: "beta",
};

const unsupportedBeach = {
  id: "unsupported",
  name: "Unsupported Beach",
  support_status: "unsupported",
};

test("model coverage excludes unsupported beaches", () => {
  assert.equal(hasModelCoverage(modeledBeach), true);
  assert.equal(hasModelCoverage(betaBeach), true);
  assert.equal(hasModelCoverage(unsupportedBeach), false);
});

test("modeled beach filters preserve eligible beaches and hide unsupported beaches", () => {
  assert.deepEqual(
    filterModeledBeaches([unsupportedBeach, modeledBeach, betaBeach]).map((beach) => beach.id),
    ["modeled", "beta"]
  );
});

test("direct lookup treats unsupported beaches as hidden", () => {
  assert.equal(findModeledBeach([unsupportedBeach, modeledBeach], "unsupported"), null);
  assert.equal(findModeledBeach([unsupportedBeach, modeledBeach], "modeled")?.id, "modeled");
  assert.equal(findModeledBeach([unsupportedBeach, modeledBeach], undefined)?.id, "modeled");
});
