import { BeachExplorer } from "@/components/BeachExplorer";
import { CaliforniaShelfMap } from "@/components/CaliforniaShelfMap";
import { RiskBadge } from "@/components/RiskBadge";
import { getBeaches, getForecast, preferredForecastDate } from "@/lib/api";

export default async function HomePage() {
  const forecastDate = preferredForecastDate();
  const beaches = await getBeaches();
  const forecasts = await Promise.all(
    beaches.map(async (beach) => {
      try {
        const forecast = await getForecast(beach.id, forecastDate);
        return [beach.id, forecast] as const;
      } catch {
        return [beach.id, null] as const;
      }
    })
  );

  const forecastMap = Object.fromEntries(forecasts);
  const riskLookup = Object.fromEntries(
    forecasts
      .filter((entry): entry is readonly [string, NonNullable<(typeof entry)[1]>] => entry[1] !== null)
      .map(([beachId, forecast]) => [beachId, forecast.risk_band])
  );

  return (
    <main className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Live Daily Forecasts</p>
          <h1>Don&apos;t judge a session by swell alone.</h1>
          <p className="hero-lede">
            Surf Health turns sparse official bacteria samples plus ocean and weather context into a
            daily health-risk forecast for California marine beaches.
          </p>
          <div className="hero-stats">
            <div>
              <span className="metric">{beaches.length}</span>
              <span className="metric-label">fixture-backed stations live in the starter build</span>
            </div>
            <div>
              <span className="metric">5:00 AM PT</span>
              <span className="metric-label">daily forecast publish target</span>
            </div>
            <div>
              <RiskBadge band="High" />
              <span className="metric-label">bands calibrated for public-facing alerts</span>
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
              and calibrated exceedance forecasts from strong baselines plus an experimental neural
              track.
            </p>
          </article>
        </div>
      </section>

      <BeachExplorer beaches={beaches} risks={riskLookup} />

      <section className="panel spotlight-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Today&apos;s forecast</p>
            <h2>What the API is serving right now</h2>
          </div>
        </div>
        <div className="spotlight-grid">
          {beaches.map((beach) => {
            const forecast = forecastMap[beach.id];
            if (!forecast) return null;
            return (
              <article key={beach.id} className="spotlight-card">
                <div className="card-topline">
                  <span>{beach.name}</span>
                  <RiskBadge band={forecast.risk_band} />
                </div>
                <p className="muted">{forecast.top_drivers.join(" • ")}</p>
                <dl>
                  <div>
                    <dt>Chance of exceedance</dt>
                    <dd>{Math.round(forecast.p_exceed * 100)}%</dd>
                  </div>
                  <div>
                    <dt>Wave height</dt>
                    <dd>{forecast.environmental_summary.wave_height_m ?? "n/a"} m</dd>
                  </div>
                  <div>
                    <dt>Salinity</dt>
                    <dd>{forecast.environmental_summary.salinity_psu ?? "n/a"} PSU</dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
