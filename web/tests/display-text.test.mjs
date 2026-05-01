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
