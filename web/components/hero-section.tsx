import Link from "next/link";

import { DropRow, SeverityBar, BetaNotice } from "@/components/RiskComponents";
import { featuredMapSite, siteStats } from "@/lib/curated";
import { advisoryProbabilityPresentation, forecastDisplayCopy } from "@/lib/forecastPresentation";
import { RISK_TOKEN } from "@/lib/riskData";
import {
  formatPacificTimestamp,
  formatRelativeSampleDate,
  formatWaterFahrenheit,
  formatWaveFeet,
} from "@/lib/utils";

export function HeroSection() {
  const stats = siteStats();
  const featuredSite = featuredMapSite();
  const forecast = featuredSite.forecast;
  const answerCopy = forecast ? forecastDisplayCopy(forecast, forecast.risk_band) : null;
  const probability = advisoryProbabilityPresentation(forecast);
  const answerToken = forecast ? RISK_TOKEN[forecast.risk_band] : null;
  const featuredBeach = featuredSite.latest_modeled_beach;
  const showResearchBanner = stats.publicReleaseEligible === false;

  return (
    <section className="site-shell overflow-hidden border-b border-[var(--sl-line)]">
      <div className="mx-auto max-w-7xl px-4 pb-20 pt-10 sm:px-6 sm:pt-14 lg:px-8 lg:pb-24">
        <div className="max-w-3xl">
            <div className="sl-eyebrow text-[var(--sl-sun-deep)]">
              Daily beta forecast · {formatPacificTimestamp(stats.latestPublishAt)}
            </div>

            {showResearchBanner && (
              <div className="mt-5 rounded-[1.25rem] border border-[var(--sl-line)] bg-[var(--sl-ecru-deep)] px-5 py-4 text-sm text-[var(--sl-ink)]">
                <div className="sl-label text-[var(--sl-muted)]">Research prototype</div>
                <div className="mt-2 leading-6">
                  This model is <span className="font-semibold text-[var(--sl-navy)]">not eligible for public release</span>{" "}
                  under its own gates. Always defer to active health advisories.
                  {stats.agreementRate != null && stats.agreementPool && (
                    <>
                      {" "}
                      {stats.agreementPool === "acute" ? "Acute" : "Chronic"}-pool advisory agreement:{" "}
                      <span className="font-semibold">{Math.round(stats.agreementRate * 100)}%</span>.
                    </>
                  )}
                </div>
                {stats.promotionBlocker && (
                  <div className="mt-2 text-xs text-[var(--sl-muted)]">{stats.promotionBlocker}</div>
                )}
              </div>
            )}

            <h1 className="sl-display mt-5 max-w-[12ch] text-[clamp(3.3rem,7vw,6.4rem)] text-[var(--sl-navy-ink)]">
              Know before you paddle out.
            </h1>

            <p className="mt-6 max-w-xl text-lg leading-8 text-[var(--sl-ink)] sm:text-xl">
              Shorelife turns official bacteria samples and coastal conditions into one-day
              health forecasts for{" "}
              <span className="font-semibold text-[var(--sl-navy)]">
                {stats.activeForecastGroups} actively modeled beach groups
              </span>{" "}
              shown on today's default map.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/beaches"
                className="sl-label inline-flex items-center justify-center rounded-full bg-[var(--sl-navy)] px-6 py-3 text-[var(--sl-bone)] transition-transform hover:-translate-y-0.5"
              >
                Open beach explorer
              </Link>
              <Link
                href="/methodology"
                className="sl-label inline-flex items-center justify-center rounded-full border border-[var(--sl-line)] bg-[var(--sl-bone)] px-6 py-3 text-[var(--sl-navy)] transition-colors hover:border-[var(--sl-navy)]"
              >
                Read methodology
              </Link>
            </div>

            <div className="paper-panel mt-9 rounded-[2rem] p-6 sm:p-8">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="sl-label text-[var(--sl-muted)]">Featured beach</div>
                  <h2 className="mt-3 text-2xl font-medium text-[var(--sl-navy)] sm:text-3xl">
                    {featuredSite.name}
                  </h2>
                  <p className="mt-2 text-sm text-[var(--sl-muted)]">
                    {featuredSite.county} County · {featuredSite.region}
                  </p>
                </div>
                {forecast && answerCopy && answerToken ? (
                  <div
                    className="rounded-[1.5rem] border px-4 py-4 sm:px-5"
                    style={{
                      background: answerToken.bg,
                      borderColor: answerToken.c,
                      color: answerToken.ink,
                    }}
                  >
                    <div className="flex items-center gap-3">
                      <DropRow band={forecast.risk_band} size={14} />
                      <div className="sl-label">{forecast.risk_band}</div>
                    </div>
                    <div className="sl-display mt-3 text-3xl">{answerCopy.headline}</div>
                    <div className="mt-2 max-w-[12rem] text-sm leading-6 opacity-85">
                      {answerCopy.body}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-[1.5rem] border border-[var(--sl-line)] bg-[var(--sl-ecru-deep)] px-4 py-4 text-sm text-[var(--sl-muted)]">
                    Forecast unavailable
                  </div>
                )}
              </div>

              {forecast && answerCopy && answerToken && (
                <>
                  <div className="mt-7">
                    <SeverityBar band={forecast.risk_band} width="100%" height={7} />
                  </div>

                  <div className="mt-4 grid gap-4 border-t border-[var(--sl-line-soft)] pt-4 sm:grid-cols-2">
                    <div>
                      <div className="sl-label text-[var(--sl-muted)]">{probability.primaryLabel}</div>
                      <div className="mt-2 text-lg font-medium text-[var(--sl-ink)]">
                        {probability.primaryPercent ?? "--"}%
                      </div>
                      {probability.secondaryLabel && (
                        <div className="mt-1 text-xs text-[var(--sl-muted)]">
                          {probability.secondaryLabel}: {probability.secondaryPercent ?? "--"}%
                        </div>
                      )}
                    </div>
                    <div>
                      <div className="sl-label text-[var(--sl-muted)]">Latest official sample</div>
                      <div className="mt-2 text-lg font-medium text-[var(--sl-ink)]">
                        {formatRelativeSampleDate(featuredSite.latest_official_sample_at)}
                      </div>
                    </div>
                    <div>
                      <div className="sl-label text-[var(--sl-muted)]">Wave height</div>
                      <div className="mt-2 text-lg font-medium text-[var(--sl-ink)]">
                        {formatWaveFeet(featuredSite.env?.wave_height_m)}
                      </div>
                    </div>
                    <div>
                      <div className="sl-label text-[var(--sl-muted)]">Water temperature</div>
                      <div className="mt-2 text-lg font-medium text-[var(--sl-ink)]">
                        {formatWaterFahrenheit(featuredSite.env?.water_temperature_c)}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-[var(--sl-line-soft)] pt-4 text-sm text-[var(--sl-muted)]">
                    <span className="sl-mono">{stats.productionModel ?? "Unknown model"}</span>
                    <BetaNotice isBeta={true} />
                    {featuredBeach?.forecast?.top_drivers?.[0] && <span>·</span>}
                    {featuredBeach?.forecast?.top_drivers?.[0] && (
                      <span>{featuredBeach.forecast.top_drivers[0]}</span>
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="mt-8 grid gap-4 sm:grid-cols-3">
              {[
                { value: stats.activeForecastGroups, label: "forecast groups shown" },
                { value: stats.modeledStations, label: "modeled stations" },
                {
                  value: `${Math.round(stats.groupedForecastCoverage * 100)}%`,
                  label: "grouped coast coverage",
                },
              ].map((stat) => (
                <div key={stat.label} className="border-t border-[var(--sl-line)] pt-4">
                  <div className="sl-display text-3xl text-[var(--sl-navy)] sm:text-4xl">
                    {stat.value}
                  </div>
                  <div className="sl-label mt-2 text-[var(--sl-muted)]">{stat.label}</div>
                </div>
              ))}
            </div>
        </div>
      </div>
    </section>
  );
}
