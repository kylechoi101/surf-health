import Link from "next/link";

import { BetaNotice, RiskChip } from "@/components/RiskComponents";
import { featuredBeaches, publicRegions } from "@/lib/curated";
import { formatPercent, formatWaterFahrenheit, formatWaveFeet } from "@/lib/utils";

export function ForecastSection() {
  const regions = publicRegions();
  const beaches = featuredBeaches(6);

  return (
    <section id="forecast" className="border-b border-[var(--sl-line)] bg-[var(--sl-bone)]">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
        <div className="max-w-3xl">
          <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Today&apos;s beta forecast</div>
          <h2 className="sl-display mt-4 text-4xl text-[var(--sl-navy-ink)] sm:text-5xl">
            What the coast looks like right now.
          </h2>
          <p className="mt-5 text-lg leading-8 text-[var(--sl-muted)]">
            Regional cards summarize modeled coverage. Spotlight cards below point to real beaches
            in today&apos;s export, not placeholder marketing content.
          </p>
        </div>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {regions.map((region) => (
            <article key={region.region} className="paper-panel rounded-[1.75rem] p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Region</div>
                  <h3 className="mt-3 text-2xl font-medium text-[var(--sl-navy)]">{region.region}</h3>
                </div>
                <div className="rounded-full bg-[var(--sl-ecru-deep)] px-3 py-1 text-sm text-[var(--sl-navy)]">
                  {region.high_risk_count} elevated
                </div>
              </div>

              <div className="mt-6 grid grid-cols-2 gap-4 border-t border-[var(--sl-line-soft)] pt-5">
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Modeled sites</div>
                  <div className="mt-2 text-2xl font-medium text-[var(--sl-ink)]">
                    {region.modeled_site_count}
                  </div>
                  <div className="mt-1 text-sm text-[var(--sl-muted)]">
                    of {region.monitored_site_count} monitored
                  </div>
                </div>
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Wave average</div>
                  <div className="mt-2 text-2xl font-medium text-[var(--sl-ink)]">
                    {formatWaveFeet(region.avg_wave_height_m)}
                  </div>
                </div>
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Water average</div>
                  <div className="mt-2 text-2xl font-medium text-[var(--sl-ink)]">
                    {formatWaterFahrenheit(region.avg_water_temp_c)}
                  </div>
                </div>
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Coverage</div>
                  <div className="mt-2 text-2xl font-medium text-[var(--sl-ink)]">
                    {Math.round((region.modeled_site_count / region.monitored_site_count) * 100)}%
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        <div className="mt-14 flex items-end justify-between gap-4">
          <div>
            <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Beach spotlights</div>
            <h3 className="sl-display mt-3 text-3xl text-[var(--sl-navy-ink)] sm:text-4xl">
              Open a real beach card.
            </h3>
          </div>
          <Link href="/beaches" className="sl-label hidden text-[var(--sl-navy)] sm:block">
            View all beaches
          </Link>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {beaches.map((beach) => (
            <Link
              key={beach.id}
              href={`/beaches/${beach.id}`}
              className="paper-panel group rounded-[1.75rem] p-6 transition-transform hover:-translate-y-1"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">{beach.county} County</div>
                  <h4 className="mt-3 text-2xl font-medium text-[var(--sl-navy)]">{beach.name}</h4>
                  <p className="mt-2 text-sm text-[var(--sl-muted)]">{beach.region}</p>
                </div>
                {beach.forecast && (
                  <div className="flex flex-col items-end gap-2">
                    <RiskChip band={beach.forecast.risk_band} />
                    <BetaNotice isBeta={beach.forecast.is_beta_forecast !== false} />
                  </div>
                )}
              </div>

              <div className="mt-5 grid grid-cols-3 gap-3 border-t border-[var(--sl-line-soft)] pt-4">
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Risk</div>
                  <div className="mt-2 text-sm font-medium text-[var(--sl-ink)]">
                    {formatPercent(beach.forecast?.p_exceed)}
                  </div>
                </div>
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Wave</div>
                  <div className="mt-2 text-sm font-medium text-[var(--sl-ink)]">
                    {formatWaveFeet(beach.env?.wave_height_m)}
                  </div>
                </div>
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Water</div>
                  <div className="mt-2 text-sm font-medium text-[var(--sl-ink)]">
                    {formatWaterFahrenheit(beach.env?.water_temperature_c)}
                  </div>
                </div>
              </div>

              {beach.forecast?.top_drivers?.[0] && (
                <p className="mt-4 text-sm leading-6 text-[var(--sl-muted)]">
                  {beach.forecast.top_drivers[0]}
                </p>
              )}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
