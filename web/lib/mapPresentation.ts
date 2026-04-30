export type MapDisplayMode = "forecast" | "all";

type RiskBandName = "Low" | "Moderate" | "High" | "Very High";

type ForecastLike = {
  risk_band?: RiskBandName;
} | null;

type EnvLike = object | null | undefined;

export type MapPresentationSite = {
  id: string;
  name?: string;
  forecast?: ForecastLike;
  modeled_member_count?: number;
  station_count?: number;
  latest_official_sample_at?: string | null;
};

export type MapMemberCandidate = {
  latest_official_sample_at?: string | null;
  env?: EnvLike;
};

export type MapSectionStatsInput = {
  totalStations: number;
  modeledStations: number;
  groupedCoastSites: number;
};

const RISK_PRIORITY: Record<RiskBandName, number> = {
  Low: 1,
  Moderate: 2,
  High: 3,
  "Very High": 4,
};

function sampleTime(value: string | null | undefined) {
  if (!value) {
    return -1;
  }

  const time = new Date(value).getTime();
  return Number.isNaN(time) ? -1 : time;
}

function envCompleteness(env: EnvLike) {
  if (!env) {
    return 0;
  }

  return Object.values(env).filter((value) => value !== null && value !== undefined).length;
}

export function hasModeledCoverage(site: MapPresentationSite) {
  return Boolean(site.forecast) && (site.modeled_member_count ?? 0) > 0;
}

export function getInitialMapSelection<T extends MapPresentationSite>(sites: T[]) {
  return (
    sites.find((site) => hasModeledCoverage(site)) ??
    sites.find((site) => Boolean(site.latest_official_sample_at)) ??
    sites[0] ??
    null
  );
}

export function getVisibleMapSites<T extends MapPresentationSite>(
  sites: T[],
  mode: MapDisplayMode
) {
  if (mode === "forecast") {
    return sites.filter((site) => hasModeledCoverage(site));
  }

  return sites;
}

export function getMapSectionStats(stats: MapSectionStatsInput) {
  return [
    { value: stats.totalStations, label: "monitoring stations" },
    { value: stats.modeledStations, label: "modeled sites" },
    { value: stats.groupedCoastSites, label: "grouped coast sites" },
  ];
}

function markerPriority(site: MapPresentationSite, activeSiteId?: string | null) {
  if (activeSiteId && site.id === activeSiteId) {
    return 100;
  }

  if (!hasModeledCoverage(site)) {
    return 0;
  }

  const riskPriority = site.forecast?.risk_band ? RISK_PRIORITY[site.forecast.risk_band] : 1;
  return 10 + riskPriority;
}

export function getMarkerRenderSites<T extends MapPresentationSite>(
  sites: T[],
  mode: MapDisplayMode,
  activeSiteId?: string | null
) {
  return [...getVisibleMapSites(sites, mode)].sort((left, right) => {
    const priorityDelta = markerPriority(left, activeSiteId) - markerPriority(right, activeSiteId);
    if (priorityDelta !== 0) {
      return priorityDelta;
    }

    const modeledDelta = (left.modeled_member_count ?? 0) - (right.modeled_member_count ?? 0);
    if (modeledDelta !== 0) {
      return modeledDelta;
    }

    return (left.name ?? left.id).localeCompare(right.name ?? right.id);
  });
}

export function getLatestOfficialSampleMember<T extends MapMemberCandidate>(members: T[]) {
  return (
    [...members]
      .filter((member) => Boolean(member.latest_official_sample_at))
      .sort(
        (left, right) =>
          sampleTime(right.latest_official_sample_at) - sampleTime(left.latest_official_sample_at)
      )[0] ?? null
  );
}

export function getBestEnvMember<T extends MapMemberCandidate>(members: T[]) {
  return (
    [...members]
      .filter((member) => envCompleteness(member.env) > 0)
      .sort((left, right) => {
        const completenessDelta = envCompleteness(right.env) - envCompleteness(left.env);
        if (completenessDelta !== 0) {
          return completenessDelta;
        }

        return sampleTime(right.latest_official_sample_at) - sampleTime(left.latest_official_sample_at);
      })[0] ?? null
  );
}
