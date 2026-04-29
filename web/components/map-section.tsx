import { CoastalMap } from "@/components/coastal-map";
import { siteForMap, siteStats } from "@/lib/curated";

export function MapSection() {
  const sites = siteForMap();
  const stats = siteStats();

  return (
    <section id="map" className="border-b border-[var(--sl-line)] bg-[var(--sl-ecru)]">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-end">
          <div className="max-w-2xl">
            <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Monitoring network</div>
            <h2 className="sl-display mt-4 text-4xl text-[var(--sl-navy-ink)] sm:text-5xl">
              Grouped sites across the California coast.
            </h2>
            <p className="mt-5 text-lg leading-8 text-[var(--sl-muted)]">
              The public map groups 924 monitoring stations into {stats.groupedCoastSites} readable
              coast sites. Markers show the latest modeled risk where coverage exists and stay
              neutral where Shorelife still falls back to official sampling only.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {[
              { value: stats.totalStations, label: "monitoring stations" },
              { value: stats.modeledStations, label: "modeled stations" },
              { value: stats.unsupportedStations, label: "official-sample only" },
            ].map((stat) => (
              <div key={stat.label} className="paper-panel rounded-[1.5rem] p-5">
                <div className="sl-display text-3xl text-[var(--sl-navy)]">{stat.value}</div>
                <div className="sl-label mt-3 text-[var(--sl-muted)]">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-10 h-[40rem]">
          <CoastalMap sites={sites} />
        </div>
      </div>
    </section>
  );
}
