import assert from "node:assert/strict";
import test from "node:test";

import {
  filterModeledBeaches,
  firstModeledBeach,
  hasModelCoverage,
} from "../lib/coverage.ts";

const modeledBeach = {
  id: "modeled",
  name: "Modeled Beach",
  support_status: "production",
};

const unsupportedBeach = {
  id: "unsupported",
  name: "Unsupported Beach",
  support_status: "unsupported",
};

test("mobile model coverage excludes unsupported beaches", () => {
  assert.equal(hasModelCoverage(modeledBeach), true);
  assert.equal(hasModelCoverage(unsupportedBeach), false);
});

test("mobile filters remove beaches that would show no model coverage", () => {
  assert.deepEqual(
    filterModeledBeaches([unsupportedBeach, modeledBeach]).map((beach) => beach.id),
    ["modeled"]
  );
});

test("mobile fallback selections skip unsupported beaches", () => {
  assert.equal(firstModeledBeach([unsupportedBeach, modeledBeach])?.id, "modeled");
  assert.equal(firstModeledBeach([unsupportedBeach]), null);
});
