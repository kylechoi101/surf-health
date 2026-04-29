"use client";

import { useState } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";

const geoUrl = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";

import { ParentBeach } from "@/lib/curated";

const bacteriaColors = {
  Low: "#059669",
  Moderate: "#d97706",
  High: "#dc2626",
};

export function CoastalMap({ sites }: { sites: ParentBeach[] }) {
  const [selectedSite, setSelectedSite] = useState<ParentBeach | null>(null);
  const [position, setPosition] = useState<{ coordinates: [number, number]; zoom: number }>({
    coordinates: [-119.5, 37.5],
    zoom: 5,
  });

  const handleMoveEnd = (pos: { coordinates: [number, number]; zoom: number }) => {
    setPosition(pos);
  };

  return (
    <div className="relative w-full h-full min-h-[500px] bg-[#0c4a6e]/5 rounded overflow-hidden border border-border/50">
      <ComposableMap
        projection="geoAlbersUsa"
        projectionConfig={{
          scale: 1200,
        }}
        className="w-full h-full"
      >
        <ZoomableGroup
          center={position.coordinates}
          zoom={position.zoom}
          onMoveEnd={handleMoveEnd}
          minZoom={3}
          maxZoom={12}
        >
          <Geographies geography={geoUrl}>
            {({ geographies }) =>
              geographies.map((geo) => {
                const isCA = geo.properties.name === "California";
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    fill={isCA ? "#d4a574" : "#e5e7eb"}
                    stroke={isCA ? "#b8845e" : "#d1d5db"}
                    strokeWidth={0.5}
                    style={{
                      default: { outline: "none" },
                      hover: { fill: isCA ? "#c9956c" : "#e5e7eb", outline: "none" },
                      pressed: { outline: "none" },
                    }}
                  />
                );
              })
            }
          </Geographies>
          
          {/* Pacific Ocean label */}
          <text
            x={-130}
            y={38}
            fontSize={4}
            fill="#0891b2"
            fontWeight="300"
            letterSpacing="0.3"
            opacity={0.6}
          >
            PACIFIC OCEAN
          </text>
          
          {sites.map((site) => (
            <Marker
              key={site.id}
              coordinates={[site.longitude, site.latitude]}
              onClick={() => setSelectedSite(site)}
            >
              <g className="cursor-pointer">
                <circle
                  r={2}
                  fill="#0c4a6e"
                  stroke="#fff"
                  strokeWidth={1}
                  className="transition-all duration-200 hover:scale-150"
                />
              </g>
            </Marker>
          ))}
        </ZoomableGroup>
      </ComposableMap>
      
      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-background/95 backdrop-blur-sm rounded p-4 border border-border/50 shadow-sm">
        <p className="text-xs font-medium text-foreground mb-3">Bacteria Levels</p>
        <div className="flex flex-col gap-2">
          {Object.entries(bacteriaColors).map(([level, color]) => (
            <div key={level} className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-xs text-muted-foreground">{level}</span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-3 pt-2 border-t border-border/50">
          CFU/100mL indicator organisms
        </p>
      </div>
      
      {/* Site Info Panel */}
      {selectedSite && (
        <div className="absolute top-4 right-4 bg-background/95 backdrop-blur-sm rounded p-5 border border-border/50 shadow-sm w-72">
          <button
            onClick={() => setSelectedSite(null)}
            className="absolute top-3 right-3 text-muted-foreground hover:text-foreground transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
          
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">{selectedSite.county} County</span>
          </div>
          
          <h4 className="text-lg font-medium text-foreground mb-4">{selectedSite.name}</h4>
          
          {/* Site Data */}
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2 border-b border-border/50">
              <span className="text-sm text-muted-foreground">Region</span>
              <span className="text-sm font-medium text-foreground">{selectedSite.region}</span>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-border/50">
              <span className="text-sm text-muted-foreground">Sub-stations</span>
              <span className="text-sm font-medium text-foreground">{selectedSite.station_count}</span>
            </div>
          </div>
          
          <div className="mt-4 p-3 bg-muted/30 border border-border/50 rounded">
            <p className="text-xs text-muted-foreground">
              Select in search to view detailed forecast.
            </p>
          </div>
        </div>
      )}
      
      {/* Zoom Controls */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-1">
        <button
          onClick={() => setPosition(p => ({ ...p, zoom: Math.min(p.zoom * 1.4, 12) }))}
          className="w-8 h-8 bg-background/95 backdrop-blur-sm rounded border border-border/50 flex items-center justify-center text-foreground hover:bg-muted transition-colors text-sm"
        >
          +
        </button>
        <button
          onClick={() => setPosition(p => ({ ...p, zoom: Math.max(p.zoom / 1.4, 3) }))}
          className="w-8 h-8 bg-background/95 backdrop-blur-sm rounded border border-border/50 flex items-center justify-center text-foreground hover:bg-muted transition-colors text-sm"
        >
          -
        </button>
      </div>
    </div>
  );
}
