"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";

import { MapSite } from "@/lib/curated";
import { RISK_TOKEN } from "@/lib/riskData";
import { formatPercent, formatWaveFeet, formatWaterFahrenheit } from "@/lib/utils";

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

export function CoastalMap({ sites }: { sites: MapSite[] }) {
  const [selectedSite, setSelectedSite] = useState<MapSite | null>(sites[0] ?? null);
  const [position, setPosition] = useState<{ coordinates: [number, number]; zoom: number }>({
    coordinates: [-119.3, 36.9],
    zoom: 5,
  });

  const sortedSites = useMemo(
    () =>
      [...sites].sort((left, right) => {
        if (left.support_status === right.support_status) {
          return right.modeled_member_count - left.modeled_member_count;
        }
        return left.support_status === "production" ? -1 : 1;
      }),
    [sites]
  );

  return (
    <div className="paper-panel relative h-full min-h-[32rem] overflow-hidden rounded-[2rem]">
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

          {sortedSites.map((site) => {
            const active = selectedSite?.id === site.id;
            const fill = markerColor(site);

            return (
              <Marker
                key={site.id}
                coordinates={[site.longitude, site.latitude]}
                onClick={() => setSelectedSite(site)}
              >
                <g className="cursor-pointer">
                  {active && <circle r={9} fill={fill} opacity={0.18} />}
                  <circle
                    r={active ? 4.2 : 2.6}
                    fill={fill}
                    stroke="var(--sl-bone)"
                    strokeWidth={active ? 1.6 : 1}
                  />
                </g>
              </Marker>
            );
          })}
        </ZoomableGroup>
      </ComposableMap>

      <div className="absolute left-4 top-4 max-w-xs rounded-2xl border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] p-4 shadow-sm backdrop-blur">
        <div className="sl-label text-[var(--sl-muted)]">Grouped coast sites</div>
        <p className="mt-2 text-sm leading-6 text-[var(--sl-ink)]">
          Click a marker to inspect the grouped beach name, modeled member count, and whether the
          latest exported forecast has model coverage.
        </p>
      </div>

      <div className="absolute bottom-4 left-4 rounded-2xl border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] p-4 shadow-sm backdrop-blur">
        <div className="sl-label text-[var(--sl-muted)]">Legend</div>
        <div className="mt-3 flex flex-col gap-2 text-sm text-[var(--sl-muted)]">
          {[
            { label: "Low", color: RISK_TOKEN.Low.c },
            { label: "Moderate", color: RISK_TOKEN.Moderate.c },
            { label: "High / Very High", color: RISK_TOKEN.High.c },
            { label: "No model coverage", color: "rgba(94, 107, 115, 0.9)" },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {selectedSite && (
        <div className="absolute right-4 top-4 w-[19rem] rounded-[1.75rem] border border-[var(--sl-line)] bg-[rgba(250,246,238,0.96)] p-5 shadow-lg backdrop-blur">
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
                {selectedSite.forecast ? selectedSite.forecast.risk_band : "No coverage"}
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

          {selectedSite.latest_modeled_beach ? (
            <Link
              href={`/beaches/${selectedSite.latest_modeled_beach.id}`}
              className="sl-label mt-5 inline-flex items-center rounded-full bg-[var(--sl-navy)] px-4 py-2 text-[var(--sl-bone)]"
            >
              Open modeled beach
            </Link>
          ) : (
            <div className="mt-5 rounded-2xl border border-[var(--sl-line)] bg-[var(--sl-ecru-deep)] px-4 py-3 text-sm text-[var(--sl-muted)]">
              This grouped site has no current model coverage yet. Use the explorer to inspect the
              latest official sample instead.
            </div>
          )}
        </div>
      )}

      <div className="absolute bottom-4 right-4 flex flex-col gap-1">
        <button
          type="button"
          onClick={() =>
            setPosition((current) => ({ ...current, zoom: Math.min(current.zoom * 1.3, 11) }))
          }
          className="h-9 w-9 rounded-full border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] text-[var(--sl-navy)] shadow-sm"
        >
          +
        </button>
        <button
          type="button"
          onClick={() =>
            setPosition((current) => ({ ...current, zoom: Math.max(current.zoom / 1.3, 3) }))
          }
          className="h-9 w-9 rounded-full border border-[var(--sl-line)] bg-[rgba(250,246,238,0.94)] text-[var(--sl-navy)] shadow-sm"
        >
          −
        </button>
      </div>
    </div>
  );
}
