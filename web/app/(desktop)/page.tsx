"use client";
import { useEffect, useState } from "react";
import { BeachExplorer } from "@/components/BeachExplorer";
import { CaliforniaShelfMap } from "@/components/CaliforniaShelfMap";
import { RiskBadge } from "@/components/RiskBadge";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";

export default function HomePage() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [forecastMap, setForecastMap] = useState<Record<string, ForecastRecord | null>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const date = preferredForecastDate();
    getBeaches().then(async (bs) => {
      setBeaches(bs);
      const pairs = await Promise.all(
        bs.map(async (b) => {
          try {
            const f = await getForecast(b.id, date);
            return [b.id, f] as const;
          } catch {
            return [b.id, null] as const;
          }
        })
      );
      setForecastMap(Object.fromEntries(pairs));
    }).finally(() => setLoading(false));
  }, []);

  const riskLookup = Object.fromEntries(
    Object.entries(forecastMap)
      .filter(([, f]) => f !== null)
      .map(([id, f]) => [id, f!.risk_band])
  );

  return (
    <main className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Live Daily Forecasts</p>
          <h1>Know before you paddle out.</h1>
          <p className="hero-lede">
            Shorelife turns sparse official bacteria samples plus ocean and weather context into a
            daily health-risk forecast for California marine beaches.
          </p>
          <div className="hero-stats">
            <div>
              <span className="metric">{beaches.length || "—"}</span>
              <span className="metric-label">monitored beach stations in California</span>
            </div>
            <div>
              <span className="metric">5:00 AM PT</span>
              <span className="metric-label">daily forecast publish target</span>
            </div>
            <div>
              <RiskBadge band="High" />
              <span className="metric-label">four risk bands calibrated for public alerts</span>
            </div>
          </div>
        </div>
        <CaliforniaShelfMap beaches={beaches} />
      </section>

      <section className="panel value-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Why this matters</p>
            <h2>Health risk is the missing beach signal</h2>
          </div>
        </div>
        <div className="value-grid">
          <article>
            <h3>For surfers</h3>
            <p>
              Check a beach card that combines surf context and water-health risk before you paddle
              out with a cut, a weak immune system, or after rain.
            </p>
          </article>
          <article>
            <h3>For agencies</h3>
            <p>
              Use same-day probability estimates to prioritize field visits, spot persistent hot
              spots, and communicate uncertainty instead of waiting only on the next lab run.
            </p>
          </article>
          <article>
            <h3>For researchers</h3>
            <p>
              Compare official enterococcus labels against nearshore covariates, blocked backtests,
              and calibrated exceedance forecasts from strong baselines.
            </p>
          </article>
        </div>
      </section>

      <BeachExplorer beaches={beaches} risks={riskLookup} />

      {!loading && Object.keys(forecastMap).length > 0 && (
        <section className="panel spotlight-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Today&apos;s forecast</p>
              <h2>What&apos;s in the water right now</h2>
            </div>
          </div>
          <div className="spotlight-grid">
            {beaches.slice(0, 12).map((beach) => {
              const forecast = forecastMap[beach.id];
              if (!forecast) return null;
              return (
                <article key={beach.id} className="spotlight-card">
                  <div className="card-topline">
                    <span>{beach.name}</span>
                    <RiskBadge band={forecast.risk_band} ageHours={forecast.forecast_age_hours} />
                  </div>
                  <p className="muted">{forecast.top_drivers.slice(0, 2).join(" • ")}</p>
                  <dl>
                    <div>
                      <dt>Exceed chance</dt>
                      <dd>{Math.round(forecast.p_exceed * 100)}%</dd>
                    </div>
                    <div>
                      <dt>Wave height</dt>
                      <dd>{forecast.environmental_summary.wave_height_m != null ? `${(forecast.environmental_summary.wave_height_m * 3.28).toFixed(1)} ft` : "n/a"}</dd>
                    </div>
                  </dl>
                </article>
              );
            })}
          </div>
        </section>
      )}
    </main>
  );
}
