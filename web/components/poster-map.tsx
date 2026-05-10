import Link from "next/link";

import { DropRow } from "@/components/RiskComponents";
import { MapSite } from "@/lib/curated";
import { RISK_TOKEN } from "@/lib/riskData";
import { formatPercent } from "@/lib/utils";

const CA_PATH = `
  M 245 18
  L 460 22
  L 470 60
  L 510 80
  L 540 130
  L 555 175
  L 565 220
  L 568 265
  L 555 295
  L 540 320
  L 522 345
  L 505 372
  L 478 408
  L 452 445
  L 422 488
  L 398 522
  L 378 552
  L 355 588
  L 335 620
  L 318 648
  L 298 678
  L 280 708
  L 260 740
  L 248 765
  L 240 780
  L 80 780
  L 60 720
  L 50 660
  L 45 600
  L 50 540
  L 60 480
  L 75 420
  L 90 360
  L 110 300
  L 130 240
  L 150 180
  L 175 130
  L 200 80
  L 225 40
  Z
`;

const LAT_MIN = 32.4;
const LAT_MAX = 41.95;

function project(lat: number, lon: number) {
  const y = 22 + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 758;
  const anchors = [
    [41.9, 65],
    [41.0, 55],
    [40.0, 60],
    [39.0, 75],
    [38.5, 95],
    [38.0, 88],
    [37.7, 100],
    [37.0, 130],
    [36.5, 145],
    [36.0, 165],
    [35.5, 195],
    [35.0, 220],
    [34.5, 245],
    [34.4, 270],
    [34.0, 305],
    [33.7, 340],
    [33.4, 380],
    [33.0, 415],
    [32.8, 440],
    [32.4, 460],
  ] as const;

  let xCoast = 60;
  for (let index = 0; index < anchors.length - 1; index += 1) {
    if (lat <= anchors[index][0] && lat >= anchors[index + 1][0]) {
      const t = (anchors[index][0] - lat) / (anchors[index][0] - anchors[index + 1][0]);
      xCoast = anchors[index][1] + t * (anchors[index + 1][1] - anchors[index][1]);
      break;
    }
  }

  if (lat > 41.0) {
    xCoast = 60;
  }

  return {
    x: xCoast + 6 + (lon + 122) * -8,
    y,
  };
}

export function PosterMap({
  sites,
  featuredSite,
}: {
  sites: MapSite[];
  featuredSite: MapSite;
}) {
  return (
    <div className="paper-panel relative overflow-hidden rounded-[2rem] bg-[var(--sl-bone)] p-4 sm:p-6">
      <div className="absolute right-6 top-6 h-28 w-28 rounded-full bg-[radial-gradient(circle,_rgba(217,154,43,0.95)_0%,_rgba(160,106,19,0.9)_70%,_transparent_71%)] opacity-90" />

      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Statewide forecast board</div>
          <h3 className="sl-display mt-3 text-3xl text-[var(--sl-navy-ink)] sm:text-4xl">
            California shoreline.
          </h3>
        </div>
        <div className="sl-label hidden text-[var(--sl-muted)] sm:block">Grouped monitoring sites</div>
      </div>

      <div className="relative overflow-hidden rounded-[1.75rem] border border-[var(--sl-line)] bg-[linear-gradient(180deg,#dbe9ee_0%,#bed5db_100%)]">
        <svg
          viewBox="0 0 600 800"
          preserveAspectRatio="xMidYMid meet"
          width="100%"
          className="block aspect-[0.88] w-full"
        >
          <defs>
            <linearGradient id="shorelife-ocean" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#dbe9ee" />
              <stop offset="1" stopColor="#c2d8df" />
            </linearGradient>
            <linearGradient id="shorelife-land" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#e9dfc6" />
              <stop offset="1" stopColor="#dccca5" />
            </linearGradient>
            <pattern id="shorelife-topo" x="0" y="0" width="14" height="14" patternUnits="userSpaceOnUse">
              <circle cx="7" cy="7" r="0.6" fill="#bfa97a" opacity="0.45" />
            </pattern>
          </defs>

          <rect x="0" y="0" width="600" height="800" fill="url(#shorelife-ocean)" />
          {[34, 36, 38, 40].map((lat) => {
            const y = 22 + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 758;
            return (
              <g key={lat}>
                <line
                  x1="0"
                  y1={y}
                  x2="600"
                  y2={y}
                  stroke="#7d95aa"
                  strokeWidth="0.5"
                  strokeDasharray="2 4"
                  opacity="0.45"
                />
                <text
                  x="10"
                  y={y - 4}
                  fill="#5e6b73"
                  fontSize="9"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {lat}°N
                </text>
              </g>
            );
          })}

          <path d={CA_PATH} fill="url(#shorelife-land)" />
          <path d={CA_PATH} fill="url(#shorelife-topo)" opacity="0.5" />
          <path
            d={`
              M 225 40 L 200 80 L 175 130 L 150 180 L 130 240
              L 110 300 L 90 360 L 75 420 L 60 480 L 50 540
              L 45 600 L 50 660 L 60 720 L 80 780
            `}
            stroke="var(--sl-navy)"
            strokeWidth="1.2"
            fill="none"
            opacity="0.55"
          />

          <text
            x="392"
            y="170"
            textAnchor="middle"
            fill="#8a6e2e"
            opacity="0.22"
            style={{ fontFamily: "var(--font-display)", fontSize: 38 }}
          >
            CALIFORNIA
          </text>

          {sites.map((site) => {
            const { x, y } = project(site.latitude, site.longitude);
            const active = site.id === featuredSite.id;
            const token = site.forecast ? RISK_TOKEN[site.forecast.risk_band] : null;
            const fill = token?.c ?? "rgba(94,107,115,0.9)";

            return (
              <g key={site.id}>
                {active && <circle cx={x} cy={y} r="11" fill={fill} opacity="0.18" />}
                <circle
                  cx={x}
                  cy={y}
                  r={active ? 4.4 : 2.4}
                  fill={fill}
                  stroke="var(--sl-bone)"
                  strokeWidth={active ? 1.8 : 0.9}
                />
              </g>
            );
          })}
        </svg>

        <div className="absolute left-4 top-4 rounded-2xl border border-[var(--sl-line)] bg-[rgba(250,246,238,0.92)] px-3 py-2 shadow-sm backdrop-blur">
          <div className="sl-label text-[var(--sl-muted)]">Daily refresh</div>
          <div className="mt-1 text-sm text-[var(--sl-ink)]">
            Forecasted sites show color. Unsupported sites stay neutral.
          </div>
        </div>

        <div className="absolute bottom-4 right-4 max-w-[17rem] rounded-3xl border border-[var(--sl-line)] bg-[rgba(250,246,238,0.96)] p-4 shadow-lg backdrop-blur">
          <div className="sl-label text-[var(--sl-muted)]">{featuredSite.county} County</div>
          <h4 className="mt-2 text-xl font-medium text-[var(--sl-navy)]">{featuredSite.name}</h4>
          <div className="mt-3 flex items-center gap-3">
            {featuredSite.forecast && (
              <>
                <DropRow band={featuredSite.forecast.risk_band} size={12} />
                <div className="sl-label text-[var(--sl-navy)]">
                  {featuredSite.forecast.risk_band} (beta)
                </div>
                <div className="sl-mono text-xs text-[var(--sl-muted)]">
                  {formatPercent(featuredSite.forecast.p_exceed)} exceedance
                </div>
              </>
            )}
          </div>
          <div className="mt-4 flex items-center justify-between border-t border-[var(--sl-line-soft)] pt-3">
            <div className="text-xs text-[var(--sl-muted)]">
              {featuredSite.modeled_member_count} modeled of {featuredSite.station_count}
            </div>
            {featuredSite.latest_modeled_beach && (
              <Link
                href={`/beaches/${featuredSite.latest_modeled_beach.id}`}
                className="sl-label text-[var(--sl-navy)]"
              >
                Open beach
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
