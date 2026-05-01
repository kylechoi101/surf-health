import assert from "node:assert/strict";
import test from "node:test";

import {
  getActiveForecastGroupCount,
  getInitialMapSelection,
  getMarkerRenderSites,
  getVisibleMapSites,
} from "../lib/mapPresentation.ts";

const officialOnlySite = {
  id: "official-only",
  name: "Official Only Beach",
  support_status: "unsupported",
  modeled_member_count: 0,
  station_count: 3,
  latest_official_sample_at: "2026-04-20T09:00:00",
  forecast: null,
};

const lowForecastSite = {
  id: "low-forecast",
  name: "Low Forecast Beach",
  support_status: "production",
  modeled_member_count: 1,
  station_count: 1,
  latest_official_sample_at: "2026-04-20T09:00:00",
  forecast: { risk_band: "Low" },
};

const highForecastSite = {
  id: "high-forecast",
  name: "High Forecast Beach",
  support_status: "production",
  modeled_member_count: 2,
  station_count: 2,
  latest_official_sample_at: "2026-04-20T09:00:00",
  forecast: { risk_band: "High" },
};

test("initial map selection skips official-only sites when modeled coverage exists", () => {
  assert.equal(
    getInitialMapSelection([officialOnlySite, lowForecastSite, highForecastSite])?.id,
    "low-forecast"
  );
});

test("forecast mode hides official-only sites from the default map", () => {
  assert.deepEqual(
    getVisibleMapSites([officialOnlySite, lowForecastSite], "forecast").map((site) => site.id),
    ["low-forecast"]
  );
});

test("active forecast group count matches the default map coverage", () => {
  assert.equal(getActiveForecastGroupCount([officialOnlySite, lowForecastSite, highForecastSite]), 2);
});

test("all-sites mode still hides official-only sites and keeps the active marker last", () => {
  assert.deepEqual(
    getMarkerRenderSites(
      [highForecastSite, officialOnlySite, lowForecastSite],
      "all",
      "low-forecast"
    ).map((site) => site.id),
    ["high-forecast", "low-forecast"]
  );
});
