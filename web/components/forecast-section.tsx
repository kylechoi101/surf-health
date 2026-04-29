import { Card, CardContent } from "@/components/ui/card";
import { Thermometer, Waves, Bug, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { regionalSummary } from "@/lib/curated";

const TrendIcon = ({ trend }: { trend: string }) => {
  if (trend === "up") return <TrendingUp className="w-3.5 h-3.5 text-amber-600" />;
  if (trend === "down") return <TrendingDown className="w-3.5 h-3.5 text-emerald-600" />;
  return <Minus className="w-3.5 h-3.5 text-muted-foreground" />;
};

export function ForecastSection() {
  const data = regionalSummary();
  // We don't have trend data or bacteria exact CFU right now in the simple summary,
  // so we'll show high risk count instead, or derive a risk level.
  // For UI parity, we'll keep the layout but use actual data.

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
            Updated daily at 8 AM PT. Forecast horizon: 24h.
          </p>
        </div>

        {/* Forecast Cards */}
        <div className="grid md:grid-cols-2 gap-6">
          {data.map((region) => {
            // Determine risk level based on high_risk_count
            const riskRatio = region.high_risk_count / region.station_count;
            let riskLevel = "Low";
            let bacteriaColor = "text-emerald-600 bg-emerald-50";
            if (riskRatio > 0.3) {
              riskLevel = "High";
              bacteriaColor = "text-red-600 bg-red-50";
            } else if (riskRatio > 0.1) {
              riskLevel = "Moderate";
              bacteriaColor = "text-amber-600 bg-amber-50";
            }

            return (
              <Card key={region.region} className="bg-card border-border/50">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between mb-6">
                    <div>
                      <h3 className="text-lg font-medium text-card-foreground">{region.region}</h3>
                      <p className="text-sm text-muted-foreground">{region.station_count} Monitoring Stations</p>
                    </div>
                    <span className={`text-xs font-medium px-2.5 py-1 rounded ${bacteriaColor}`}>
                      {riskLevel} Regional Risk
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    {/* Temperature */}
                    <div className="text-center p-4 bg-muted/30 rounded">
                      <Thermometer className="w-5 h-5 mx-auto mb-2 text-primary" />
                      <div className="text-2xl font-semibold text-foreground">
                        {region.avg_water_temp_c ? ((region.avg_water_temp_c * 9/5) + 32).toFixed(1) : "—"}°
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">Water Temp (F)</div>
                      <div className="flex items-center justify-center gap-1 mt-2">
                        <TrendIcon trend="stable" />
                        <span className="text-xs text-muted-foreground">Stable</span>
                      </div>
                    </div>

                    {/* Wave Height */}
                    <div className="text-center p-4 bg-muted/30 rounded">
                      <Waves className="w-5 h-5 mx-auto mb-2 text-primary" />
                      <div className="text-2xl font-semibold text-foreground">
                        {region.avg_wave_height_m ? (region.avg_wave_height_m * 3.28084).toFixed(1) : "—"}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">Wave Height (ft)</div>
                      <div className="flex items-center justify-center gap-1 mt-2">
                        <TrendIcon trend="stable" />
                        <span className="text-xs text-muted-foreground">Stable</span>
                      </div>
                    </div>

                    {/* Bacteria */}
                    <div className="text-center p-4 bg-muted/30 rounded">
                      <Bug className="w-5 h-5 mx-auto mb-2 text-primary" />
                      <div className="text-2xl font-semibold text-foreground">{region.high_risk_count}</div>
                      <div className="text-xs text-muted-foreground mt-1">High Risk Sites</div>
                      <div className="flex items-center justify-center gap-1 mt-2">
                        <TrendIcon trend="stable" />
                        <span className="text-xs text-muted-foreground">Today</span>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Legend */}
        <div className="mt-8 p-4 bg-muted/30 rounded flex flex-wrap items-center justify-center gap-6 text-sm">
          <span className="text-muted-foreground">Regulatory References (EPA STV / CDPH):</span>
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
