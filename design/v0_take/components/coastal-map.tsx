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

interface BeachSite {
  name: string;
  coordinates: [number, number];
  temperature: number;
  waveHeight: number;
  bacteriaLevel: "Low" | "Moderate" | "High";
  bacteriaCount: number;
  region: string;
}

const californiaBeaches: BeachSite[] = [
  {
    name: "Crescent City",
    coordinates: [-124.2, 41.76],
    temperature: 54,
    waveHeight: 4.2,
    bacteriaLevel: "Low",
    bacteriaCount: 12,
    region: "Del Norte County",
  },
  {
    name: "Trinidad",
    coordinates: [-124.14, 41.06],
    temperature: 55,
    waveHeight: 3.8,
    bacteriaLevel: "Low",
    bacteriaCount: 8,
    region: "Humboldt County",
  },
  {
    name: "Point Reyes",
    coordinates: [-122.97, 38.07],
    temperature: 56,
    waveHeight: 5.1,
    bacteriaLevel: "Low",
    bacteriaCount: 15,
    region: "Marin County",
  },
  {
    name: "Ocean Beach SF",
    coordinates: [-122.51, 37.76],
    temperature: 58,
    waveHeight: 4.5,
    bacteriaLevel: "Moderate",
    bacteriaCount: 45,
    region: "San Francisco",
  },
  {
    name: "Half Moon Bay",
    coordinates: [-122.47, 37.46],
    temperature: 57,
    waveHeight: 6.2,
    bacteriaLevel: "Low",
    bacteriaCount: 18,
    region: "San Mateo County",
  },
  {
    name: "Santa Cruz",
    coordinates: [-122.03, 36.96],
    temperature: 60,
    waveHeight: 4.8,
    bacteriaLevel: "Low",
    bacteriaCount: 22,
    region: "Santa Cruz County",
  },
  {
    name: "Monterey Bay",
    coordinates: [-121.9, 36.6],
    temperature: 59,
    waveHeight: 3.5,
    bacteriaLevel: "Low",
    bacteriaCount: 10,
    region: "Monterey County",
  },
  {
    name: "Big Sur",
    coordinates: [-121.85, 36.24],
    temperature: 58,
    waveHeight: 7.2,
    bacteriaLevel: "Low",
    bacteriaCount: 5,
    region: "Monterey County",
  },
  {
    name: "Morro Bay",
    coordinates: [-120.87, 35.37],
    temperature: 61,
    waveHeight: 4.0,
    bacteriaLevel: "Moderate",
    bacteriaCount: 52,
    region: "San Luis Obispo",
  },
  {
    name: "Pismo Beach",
    coordinates: [-120.64, 35.14],
    temperature: 63,
    waveHeight: 3.8,
    bacteriaLevel: "Low",
    bacteriaCount: 28,
    region: "San Luis Obispo",
  },
  {
    name: "Santa Barbara",
    coordinates: [-119.7, 34.41],
    temperature: 65,
    waveHeight: 2.5,
    bacteriaLevel: "Low",
    bacteriaCount: 20,
    region: "Santa Barbara County",
  },
  {
    name: "Ventura",
    coordinates: [-119.29, 34.27],
    temperature: 66,
    waveHeight: 3.2,
    bacteriaLevel: "Moderate",
    bacteriaCount: 48,
    region: "Ventura County",
  },
  {
    name: "Malibu",
    coordinates: [-118.78, 34.03],
    temperature: 68,
    waveHeight: 3.5,
    bacteriaLevel: "High",
    bacteriaCount: 125,
    region: "Los Angeles County",
  },
  {
    name: "Santa Monica",
    coordinates: [-118.5, 34.01],
    temperature: 68,
    waveHeight: 2.8,
    bacteriaLevel: "Moderate",
    bacteriaCount: 62,
    region: "Los Angeles County",
  },
  {
    name: "Manhattan Beach",
    coordinates: [-118.41, 33.88],
    temperature: 69,
    waveHeight: 3.0,
    bacteriaLevel: "Low",
    bacteriaCount: 25,
    region: "Los Angeles County",
  },
  {
    name: "Huntington Beach",
    coordinates: [-117.99, 33.66],
    temperature: 70,
    waveHeight: 4.2,
    bacteriaLevel: "Moderate",
    bacteriaCount: 55,
    region: "Orange County",
  },
  {
    name: "Newport Beach",
    coordinates: [-117.93, 33.62],
    temperature: 70,
    waveHeight: 3.8,
    bacteriaLevel: "Low",
    bacteriaCount: 30,
    region: "Orange County",
  },
  {
    name: "Laguna Beach",
    coordinates: [-117.78, 33.54],
    temperature: 69,
    waveHeight: 3.2,
    bacteriaLevel: "Low",
    bacteriaCount: 18,
    region: "Orange County",
  },
  {
    name: "La Jolla",
    coordinates: [-117.27, 32.85],
    temperature: 68,
    waveHeight: 3.0,
    bacteriaLevel: "Low",
    bacteriaCount: 22,
    region: "San Diego County",
  },
  {
    name: "Mission Beach",
    coordinates: [-117.25, 32.77],
    temperature: 69,
    waveHeight: 3.5,
    bacteriaLevel: "Moderate",
    bacteriaCount: 58,
    region: "San Diego County",
  },
  {
    name: "Imperial Beach",
    coordinates: [-117.13, 32.58],
    temperature: 68,
    waveHeight: 3.2,
    bacteriaLevel: "High",
    bacteriaCount: 142,
    region: "San Diego County",
  },
];

const bacteriaColors = {
  Low: "#059669",
  Moderate: "#d97706",
  High: "#dc2626",
};

export function CoastalMap() {
  const [selectedSite, setSelectedSite] = useState<BeachSite | null>(null);
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
          
          {californiaBeaches.map((site) => (
            <Marker
              key={site.name}
              coordinates={site.coordinates}
              onClick={() => setSelectedSite(site)}
            >
              <g className="cursor-pointer">
                <circle
                  r={3}
                  fill={bacteriaColors[site.bacteriaLevel]}
                  stroke="#fff"
                  strokeWidth={1.5}
                  className="transition-all duration-200 hover:scale-150"
                />
                {site.bacteriaLevel === "High" && (
                  <circle
                    r={6}
                    fill={bacteriaColors[site.bacteriaLevel]}
                    fillOpacity={0.25}
                    className="animate-pulse"
                  />
                )}
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
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: bacteriaColors[selectedSite.bacteriaLevel] }}
            />
            <span className="text-xs text-muted-foreground">{selectedSite.region}</span>
          </div>
          
          <h4 className="text-lg font-medium text-foreground mb-4">{selectedSite.name}</h4>
          
          {/* Forecast Data */}
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2 border-b border-border/50">
              <span className="text-sm text-muted-foreground">Water Temp</span>
              <span className="text-sm font-medium text-foreground">{selectedSite.temperature}°F</span>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-border/50">
              <span className="text-sm text-muted-foreground">Wave Height</span>
              <span className="text-sm font-medium text-foreground">{selectedSite.waveHeight} ft</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Bacteria Level</span>
              <div className="flex items-center gap-2">
                <span 
                  className="text-sm font-medium"
                  style={{ color: bacteriaColors[selectedSite.bacteriaLevel] }}
                >
                  {selectedSite.bacteriaLevel}
                </span>
                <span className="text-xs text-muted-foreground">
                  ({selectedSite.bacteriaCount} CFU)
                </span>
              </div>
            </div>
          </div>
          
          {selectedSite.bacteriaLevel === "High" && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded">
              <p className="text-xs text-red-700">
                Advisory: Elevated bacteria levels detected. Swimming not recommended.
              </p>
            </div>
          )}
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
