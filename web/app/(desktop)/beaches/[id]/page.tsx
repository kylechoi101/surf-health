import { RiskBadge } from "@/components/RiskBadge";
import { getBeaches, getExplanation, getForecast, getObservations, preferredForecastDate } from "@/lib/api";
import Link from "next/link";
import { notFound } from "next/navigation";

export default async function BeachDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const beaches = await getBeaches();
  const beach = beaches.find((entry) => entry.id === id);
  if (!beach) notFound();

  const forecastDate = preferredForecastDate();
  const [forecast, observations, explanation] = await Promise.all([
    getForecast(id, forecastDate),
    getObservations(id),
    getExplanation(id, forecastDate)
  ]);

  return (
    <main className="page-shell detail-shell">
      <section className="detail-hero panel">
        <div>
          <p className="eyebrow">{beach.county} County</p>
          <h1>{beach.name}</h1>
          <p className="hero-lede">
            Forecast date {forecast.forecast_date} • Model {forecast.model_version}
          </p>
        </div>
        <div className="detail-sidecar">
          <RiskBadge band={forecast.risk_band} />
          <p>{Math.round(forecast.p_exceed * 100)}% chance of exceeding the marine threshold</p>
          <p className="muted">Latest official sample: {beach.latest_official_sample_at ?? "n/a"}</p>
        </div>
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Forecast explanation</p>
              <h2>Why this beach looks the way it does</h2>
            </div>
          </div>
          <p className="narrative">{explanation.summary}</p>
          <ul className="driver-list">
            {forecast.top_drivers.map((driver) => (
              <li key={driver}>{driver}</li>
            ))}
          </ul>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Surf context</p>
              <h2>Nearshore conditions</h2>
            </div>
          </div>
          <dl className="metric-table">
            <div>
              <dt>Wave height</dt>
              <dd>{forecast.environmental_summary.wave_height_m ?? "n/a"} m</dd>
            </div>
            <div>
              <dt>Dominant period</dt>
              <dd>{forecast.environmental_summary.dominant_period_s ?? "n/a"} s</dd>
            </div>
            <div>
              <dt>Water temperature</dt>
              <dd>{forecast.environmental_summary.water_temperature_c ?? "n/a"} °C</dd>
            </div>
            <div>
              <dt>Salinity</dt>
              <dd>{forecast.environmental_summary.salinity_psu ?? "n/a"} PSU</dd>
            </div>
            <div>
              <dt>UV index</dt>
              <dd>{forecast.environmental_summary.uv_index ?? "n/a"}</dd>
            </div>
            <div>
              <dt>Wind speed</dt>
              <dd>{forecast.environmental_summary.wind_speed_mps ?? "n/a"} m/s</dd>
            </div>
          </dl>
        </article>
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Official monitoring</p>
              <h2>Recent enterococcus samples</h2>
            </div>
          </div>
          <div className="table-shell">
            <table>
              <thead>
                <tr>
                  <th>Sample time</th>
                  <th>Method</th>
                  <th>Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {observations.observations.map((observation) => (
                  <tr key={observation.sample_time}>
                    <td>{observation.sample_time.slice(0, 10)}</td>
                    <td>{observation.method}</td>
                    <td>
                      {observation.value} {observation.units}
                    </td>
                    <td>{observation.exceeds_stv ? "Above threshold" : "Below threshold"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Advisories + traceability</p>
              <h2>Risk controls</h2>
            </div>
          </div>
          <ul className="driver-list">
            <li>Official county advisories always override model optimism.</li>
            <li>Confidence bands come from held-out calibration, not hand-tuned copy.</li>
            <li>Unsampled days are forecasted only from observed labels plus exogenous covariates.</li>
          </ul>
          <div className="notice-card">
            <strong>Active advisories</strong>
            <p>{observations.advisories.length ? observations.advisories[0].status : "None active"}</p>
          </div>
          <Link className="pill-link" href="/methodology">
            Read the methodology
          </Link>
        </article>
      </section>
    </main>
  );
}
