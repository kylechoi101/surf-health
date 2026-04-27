"use client";
import { useEffect, useState } from "react";
import { RiskBadge } from "@/components/RiskBadge";
import { getBeaches, getForecast, getSystemHealth, preferredForecastDate, type BeachSummary, type ForecastRecord, type HealthResponse } from "@/lib/api";

export default function ResearchPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [forecasts, setForecasts] = useState<{ beach: BeachSummary; forecast: ForecastRecord | null }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const date = preferredForecastDate();
    Promise.all([getSystemHealth(), getBeaches()]).then(async ([h, bs]) => {
      setHealth(h);
      setBeaches(bs);
      const fc = await Promise.all(
        bs.map(async (b) => ({
          beach: b,
          forecast: await getForecast(b.id, date).catch(() => null),
        }))
      );
      setForecasts(fc);
    }).finally(() => setLoading(false));
  }, []);

  if (loading || !health) return <main className="page-shell"><p style={{ padding: 40, color: "#64748b" }}>Loading…</p></main>;

  const productionCount = beaches.filter((b) => b.support_status === "production").length;
  const betaCount = beaches.filter((b) => b.support_status === "beta").length;
  const productionMetrics = health.model_registry.production_metrics ?? {};
  const validationMetrics = health.model_registry.validation_metrics ?? {};
  const spatialMetrics = health.model_registry.spatial_metrics ?? {};

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div className="hero-copy">
          <p className="eyebrow">Research + Ops</p>
          <h1>Model health and deployment traceability</h1>
          <p className="hero-lede">
            The operator view tracks model registry status, source freshness, and which stations are
            ready for production versus beta fallback.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Registry</p>
            <h2>Production posture</h2>
          </div>
        </div>
        <div className="value-grid">
          <article>
            <h3>Current model</h3>
            <p>{health.model_registry.production_model}</p>
          </article>
          <article>
            <h3>Test AUCPR</h3>
            <p>{typeof productionMetrics.aucpr === "number" ? productionMetrics.aucpr.toFixed(4) : "n/a"}</p>
          </article>
          <article>
            <h3>Test Brier</h3>
            <p>{typeof productionMetrics.brier === "number" ? productionMetrics.brier.toFixed(4) : "n/a"}</p>
          </article>
          <article>
            <h3>Coverage mix</h3>
            <p>{productionCount} production / {betaCount} beta</p>
          </article>
          <article>
            <h3>Public release</h3>
            <p>{health.model_registry.public_release_eligible ? "Eligible" : "Not yet"}</p>
          </article>
        </div>
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Source freshness</p>
              <h2>Pipeline heartbeat</h2>
            </div>
          </div>
          <div className="table-shell">
            <table>
              <thead>
                <tr><th>Source</th><th>Freshness</th></tr>
              </thead>
              <tbody>
                {Object.entries(health.source_freshness).map(([source, freshness]) => (
                  <tr key={source}><td>{source}</td><td>{freshness}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Station state</p>
              <h2>Current forecast coverage</h2>
            </div>
          </div>
          <div className="spotlight-grid">
            {forecasts.filter(({ forecast }) => forecast).map(({ beach, forecast }) => (
              <article key={beach.id} className="spotlight-card">
                <div className="card-topline">
                  <span>{beach.name}</span>
                  <RiskBadge band={forecast!.risk_band} ageHours={forecast!.forecast_age_hours} />
                </div>
                <p className="muted">{beach.support_status} · {beach.region}</p>
                <p>{forecast!.model_version}</p>
              </article>
            ))}
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Validation</p>
            <h2>Promotion posture</h2>
          </div>
        </div>
        <div className="value-grid">
          <article>
            <h3>Stage</h3>
            <p>{health.model_registry.deployment_stage ?? "n/a"}</p>
          </article>
          <article>
            <h3>Valid AUCPR</h3>
            <p>{typeof validationMetrics.aucpr === "number" ? validationMetrics.aucpr.toFixed(4) : "n/a"}</p>
          </article>
          <article>
            <h3>Valid Brier</h3>
            <p>{typeof validationMetrics.brier === "number" ? validationMetrics.brier.toFixed(4) : "n/a"}</p>
          </article>
          <article>
            <h3>Neural track</h3>
            <p>{health.model_registry.promotion_policy?.neural_model_status ?? "n/a"}</p>
          </article>
        </div>
        {(health.model_registry.promotion_blockers?.length ?? 0) > 0 && (
          <ul className="driver-list">
            {health.model_registry.promotion_blockers!.map((b) => <li key={b}>{b}</li>)}
          </ul>
        )}
        {Object.keys(spatialMetrics).length > 0 && (
          <div className="table-shell">
            <table>
              <thead><tr><th>Spatial holdout</th><th>AUCPR</th><th>Brier</th></tr></thead>
              <tbody>
                {Object.entries(spatialMetrics).map(([name, m]) => (
                  <tr key={name}><td>{name}</td><td>{m.aucpr ?? "n/a"}</td><td>{m.brier ?? "n/a"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
