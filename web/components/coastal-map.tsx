"use client";

import Link from "next/link";
import { Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";

import { MapSite } from "@/lib/curated";
import {
  getInitialMapSelection,
  getMarkerRenderSites,
  getVisibleMapSites,
  hasModeledCoverage,
  MapDisplayMode,
} from "@/lib/mapPresentation";
import { RISK_TOKEN } from "@/lib/riskData";
import {
  cn,
  formatPacificDate,
  formatPercent,
  formatRelativeSampleDate,
  formatWaveFeet,
  formatWaterFahrenheit,
} from "@/lib/utils";

const geoUrl = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";

type MapGeography = {
  rsmKey: string;
  properties: {
    name?: string;
  };
};

function markerColor(site: MapSite) {
  if (!site.forecast) {
    return "rgba(94, 107, 115, 0.9)";
  }
  return RISK_TOKEN[site.forecast.risk_band].c;
}

function markerOpacity(site: MapSite) {
  return hasModeledCoverage(site) ? 0.96 : 0.38;
}

export function CoastalMap({ sites }: { sites: MapSite[] }) {
  const [isMounted, setIsMounted] = useState(false);
  const [mode, setMode] = useState<MapDisplayMode>("forecast");
  const [selectedSite, setSelectedSite] = useState<MapSite | null>(() =>
    getInitialMapSelection(sites)
  );
  const [position, setPosition] = useState<{ coordinates: [number, number]; zoom: number }>({
    coordinates: [-119.3, 36.9],
    zoom: 5,
  });

  const visibleSites = useMemo(() => getVisibleMapSites(sites, mode), [mode, sites]);
  const markerSites = useMemo(
    () => getMarkerRenderSites(sites, mode, selectedSite?.id),
    [mode, selectedSite?.id, sites]
  );
  const forecastSiteCount = useMemo(
    () => sites.filter((site) => hasModeledCoverage(site)).length,
    [sites]
  );

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    setSelectedSite((current) => {
      if (current && visibleSites.some((site) => site.id === current.id)) {
        return current;
      }

      return getInitialMapSelection(visibleSites);
    });
  }, [visibleSites]);

  const selectedHasCoverage = selectedSite ? hasModeledCoverage(selectedSite) : false;

  return (
    <div className="paper-panel relative h-full min-h-[32rem] overflow-hidden rounded-[1.5rem]">
      {isMounted ? (
        <ComposableMap
          projection="geoAlbersUsa"
          projectionConfig={{ scale: 1150 }}
          className="h-full w-full bg-[linear-gradient(180deg,#dbe9ee_0%,#c2d8df_100%)]"
        >
          <ZoomableGroup
            center={position.coordinates}
            zoom={position.zoom}
            onMoveEnd={setPosition}
            minZoom={3}
            maxZoom={11}
          >
            <Geographies geography={geoUrl}>
              {({ geographies }: { geographies: MapGeography[] }) =>
                geographies.map((geo: MapGeography) => {
                  const isCalifornia = geo.properties.name === "California";
                  return (
                    <Geography
                      key={geo.rsmKey}
                      geography={geo}
                      fill={isCalifornia ? "#e4d7b9" : "#eff3f5"}
                      stroke={isCalifornia ? "#b89f6b" : "#d1d5db"}
                      strokeWidth={0.6}
                      style={{
                        default: { outline: "none" },
                        hover: { fill: isCalifornia ? "#decba3" : "#eff3f5", outline: "none" },
                        pressed: { outline: "none" },
                      }}
                    />
                  );
                })
              }
            </Geographies>

            {markerSites.map((site) => {
              const active = selectedSite?.id === site.id;
              const fill = markerColor(site);
              const modeled = hasModeledCoverage(site);

              return (
                <Marker
                  key={site.id}
                  coordinates={[site.longitude, site.latitude]}
                  onClick={() => setSelectedSite(site)}
                >
                  <g className="cursor-pointer">
                    {active && <circle r={modeled ? 9 : 7.5} fill={fill} opacity={0.2} />}
                    <circle
                      r={active ? 4.5 : modeled ? 3 : 2.2}
                      fill={fill}
                      opacity={markerOpacity(site)}
                      stroke="var(--sl-bone)"
                      strokeWidth={active ? 1.8 : modeled ? 1.1 : 0.8}
                    />
                  </g>
                </Marker>
              );
            })}
          </ZoomableGroup>
        </ComposableMap>
      ) : (
        <div className="h-full w-full animate-pulse bg-[linear-gradient(180deg,#dbe9ee_0%,#c2d8df_100%)]" />
      )}

      <div className="absolute left-3 right-3 top-3 z-10 rounded-[1rem] border border-[var(--sl-line)] bg-[rgba(250,246,238,0.95)] p-3 shadow-sm backdrop-blur sm:left-4 sm:right-auto sm:max-w-[24rem]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="sl-label text-[var(--sl-muted)]">Map view</div>
            <div className="mt-1 text-sm font-medium text-[var(--sl-navy)]">
              {mode === "forecast"
                ? `${forecastSiteCount} forecast groups`
                : `${sites.length} grouped sites`}
            </div>
          </div>

          <div className="flex rounded-full border border-[var(--sl-line)] bg-[var(--sl-bone)] p-1 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--sl-muted)]">
            {[
              { value: "forecast" as const, label: "Forecasts" },
              { value: "all" as const, label: "All sites" },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setMode(item.value)}
                className={cn(
                  "rounded-full px-3 py-2 transition",
                  mode === item.value
                    ? "bg-[var(--sl-navy)] text-[var(--sl-bone)]"
                    : "text-[var(--sl-muted)] hover:text-[var(--sl-navy)]"
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[var(--sl-muted)] sm:grid-cols-4">
          {[
            { label: "Low", color: RISK_TOKEN.Low.c },
            { label: "Moderate", color: RISK_TOKEN.Moderate.c },
            { label: "High", color: RISK_TOKEN.High.c },
            { label: "Sample only", color: "rgba(94, 107, 115, 0.9)" },
          ].map((item) => (
            <div key={item.label} className="flex min-w-0 items-center gap-2">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <span className="truncate">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {selectedSite && (
        <div className="absolute bottom-3 left-3 right-3 z-10 max-h-[18rem] overflow-y-auto rounded-[1rem] border border-[var(--sl-line)] bg-[rgba(250,246,238,0.97)] p-4 shadow-lg backdrop-blur sm:bottom-auto sm:left-auto sm:right-4 sm:top-4 sm:max-h-[calc(100%-2rem)] sm:w-[20rem] sm:p-5">
          <div className="sl-label text-[var(--sl-muted)]">{selectedSite.county} County</div>
          <h4 className="mt-2 text-2xl font-medium text-[var(--sl-navy)]">{selectedSite.name}</h4>

          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--sl-line-soft)] pt-4 text-sm">
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Modeled</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">
                {selectedSite.modeled_member_count} / {selectedSite.station_count}
              </div>
            </div>
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Region</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">{selectedSite.region}</div>
            </div>
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Risk</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">
                {selectedSite.forecast ? selectedSite.forecast.risk_band : "Sample only"}
              </div>
            </div>
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Exceed</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">
                {formatPercent(selectedSite.forecast?.p_exceed)}
              </div>
            </div>
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Wave</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">
                {formatWaveFeet(selectedSite.env?.wave_height_m)}
              </div>
            </div>
            <div>
              <div className="sl-label text-[var(--sl-muted)]">Water</div>
              <div className="mt-2 font-medium text-[var(--sl-ink)]">
                {formatWaterFahrenheit(selectedSite.env?.water_temperature_c)}
              </div>
            </div>
          </div>

          {selectedHasCoverage && selectedSite.latest_modeled_beach ? (
            <Link
              href={`/beaches/${selectedSite.latest_modeled_beach.id}`}
              className="sl-label mt-5 inline-flex items-center rounded-full bg-[var(--sl-navy)] px-4 py-2 text-[var(--sl-bone)]"
            >
              Open forecast beach
            </Link>
          ) : (
            <div className="mt-5 rounded-[0.75rem] border border-[var(--sl-line)] bg-[var(--sl-ecru-deep)] px-4 py-3 text-sm text-[var(--sl-muted)]">
              <div className="font-medium text-[var(--sl-ink)]">
                {formatRelativeSampleDate(selectedSite.latest_official_sample_at)}
              </div>
              <div className="mt-1">
                Latest official sample: {formatPacificDate(selectedSite.latest_official_sample_at)}
              </div>
              {selectedSite.latest_official_beach && (
                <Link
                  href={`/beaches/${selectedSite.latest_official_beach.id}`}
                  className="sl-label mt-3 inline-flex text-[var(--sl-navy)]"
                >
                  Open sample beach
                </Link>
              )}
            </div>
          )}
        </div>
      )}

      <div className="absolute bottom-3 right-3 z-20 flex flex-col gap-1 sm:bottom-4 sm:right-4">
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() =>
            setPosition((current) => ({ ...current, zoom: Math.min(current.zoom * 1.3, 11) }))
          }
          className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] text-[var(--sl-navy)] shadow-sm"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() =>
            setPosition((current) => ({ ...current, zoom: Math.max(current.zoom / 1.3, 3) }))
          }
          className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] text-[var(--sl-navy)] shadow-sm"
        >
          <Minus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
