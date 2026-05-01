export type CoverageTagged = {
  support_status?: string | null;
};

export function hasModelCoverage<T extends CoverageTagged>(site: T | null | undefined) {
  return site != null && site.support_status !== "unsupported";
}

export function filterModeledBeaches<T extends CoverageTagged>(sites: T[]) {
  return sites.filter((site) => hasModelCoverage(site));
}

export function firstModeledBeach<T extends CoverageTagged>(sites: T[]) {
  return filterModeledBeaches(sites)[0] ?? null;
}

export function findModeledBeach<T extends CoverageTagged & { id: string }>(
  sites: T[],
  id?: string | null
) {
  if (!id) {
    return firstModeledBeach(sites);
  }

  return filterModeledBeaches(sites).find((site) => site.id === id) ?? null;
}
