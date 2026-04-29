"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Thermometer, Waves, Bug, TrendingUp, TrendingDown, Minus } from "lucide-react";

const forecastData = [
  {
    region: "North Coast",
    beaches: "Crescent City to Point Reyes",
    temperature: { current: 55, trend: "stable", change: 0 },
    waveHeight: { current: 4.5, trend: "up", change: 1.2 },
    bacteria: { level: "Low", value: 12, trend: "stable" },
  },
  {
    region: "Bay Area",
    beaches: "San Francisco to Santa Cruz",
    temperature: { current: 58, trend: "up", change: 2 },
    waveHeight: { current: 5.2, trend: "up", change: 0.8 },
    bacteria: { level: "Moderate", value: 45, trend: "up" },
  },
  {
    region: "Central Coast",
    beaches: "Monterey to San Luis Obispo",
    temperature: { current: 61, trend: "up", change: 1 },
    waveHeight: { current: 4.8, trend: "stable", change: 0.2 },
    bacteria: { level: "Low", value: 18, trend: "down" },
  },
  {
    region: "Southern California",
    beaches: "Santa Barbara to San Diego",
    temperature: { current: 68, trend: "stable", change: 1 },
    waveHeight: { current: 3.2, trend: "down", change: -0.5 },
    bacteria: { level: "Moderate", value: 52, trend: "up" },
  },
];

const TrendIcon = ({ trend }: { trend: string }) => {
  if (trend === "up") return <TrendingUp className="w-3.5 h-3.5 text-amber-600" />;
  if (trend === "down") return <TrendingDown className="w-3.5 h-3.5 text-emerald-600" />;
  return <Minus className="w-3.5 h-3.5 text-muted-foreground" />;
};

const bacteriaColors = {
  Low: "text-emerald-600 bg-emerald-50",
  Moderate: "text-amber-600 bg-amber-50",
  High: "text-red-600 bg-red-50",
};

export function ForecastSection() {
  return (
    <section id="forecast" className="py-24 bg-background relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-2xl mb-12">
          <span className="text-primary text-sm tracking-widest uppercase font-medium">
            Today&apos;s Forecast
          </span>
          <h2 className="text-3xl md:text-4xl font-light mt-4 mb-6 text-foreground text-balance">
            California Coastal
            <span className="font-semibold"> Conditions</span>
          </h2>
          <p className="text-muted-foreground leading-relaxed">
            Current water quality data aggregated from monitoring stations along the California coastline. 
            Updated every 6 hours with 48-hour forecasting.
          </p>
        </div>

        {/* Forecast Cards */}
        <div className="grid md:grid-cols-2 gap-6">
          {forecastData.map((region) => (
            <Card key={region.region} className="bg-card border-border/50">
              <CardContent className="p-6">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <h3 className="text-lg font-medium text-card-foreground">{region.region}</h3>
                    <p className="text-sm text-muted-foreground">{region.beaches}</p>
                  </div>
                  <span className={`text-xs font-medium px-2.5 py-1 rounded ${bacteriaColors[region.bacteria.level as keyof typeof bacteriaColors]}`}>
                    {region.bacteria.level} Risk
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  {/* Temperature */}
                  <div className="text-center p-4 bg-muted/30 rounded">
                    <Thermometer className="w-5 h-5 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-semibold text-foreground">{region.temperature.current}°</div>
                    <div className="text-xs text-muted-foreground mt-1">Water Temp (F)</div>
                    <div className="flex items-center justify-center gap-1 mt-2">
                      <TrendIcon trend={region.temperature.trend} />
                      <span className="text-xs text-muted-foreground">
                        {region.temperature.change > 0 ? "+" : ""}{region.temperature.change}°
                      </span>
                    </div>
                  </div>

                  {/* Wave Height */}
                  <div className="text-center p-4 bg-muted/30 rounded">
                    <Waves className="w-5 h-5 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-semibold text-foreground">{region.waveHeight.current}</div>
                    <div className="text-xs text-muted-foreground mt-1">Wave Height (ft)</div>
                    <div className="flex items-center justify-center gap-1 mt-2">
                      <TrendIcon trend={region.waveHeight.trend} />
                      <span className="text-xs text-muted-foreground">
                        {region.waveHeight.change > 0 ? "+" : ""}{region.waveHeight.change} ft
                      </span>
                    </div>
                  </div>

                  {/* Bacteria */}
                  <div className="text-center p-4 bg-muted/30 rounded">
                    <Bug className="w-5 h-5 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-semibold text-foreground">{region.bacteria.value}</div>
                    <div className="text-xs text-muted-foreground mt-1">CFU/100mL</div>
                    <div className="flex items-center justify-center gap-1 mt-2">
                      <TrendIcon trend={region.bacteria.trend} />
                      <span className="text-xs text-muted-foreground">
                        {region.bacteria.trend === "up" ? "Rising" : region.bacteria.trend === "down" ? "Falling" : "Stable"}
                      </span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Legend */}
        <div className="mt-8 p-4 bg-muted/30 rounded flex flex-wrap items-center justify-center gap-6 text-sm">
          <span className="text-muted-foreground">Bacteria Risk Levels:</span>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-muted-foreground">Low (&lt;35 CFU)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-muted-foreground">Moderate (35-104 CFU)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-muted-foreground">High (&gt;104 CFU)</span>
          </div>
        </div>
      </div>
    </section>
  );
}
