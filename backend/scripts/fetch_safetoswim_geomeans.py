"""Fetch the Safe-to-Swim CEDEN geomeans resource via the CKAN datastore API.

Replaces the previous `curl` of the raw CSV download URL, which is unreliable:
data.ca.gov's CKAN file-store occasionally returns a 302 with a malformed
`Location:` header pointing the filename as the host (e.g.
`location: http://SafeToSwim_geomeans_2020-present.csv`), which curl can't
follow. The underlying datastore JSON API stays healthy through these
incidents, so we pull from there and assemble the CSV ourselves.

Only rows with a bacterial-indicator analyte are kept — the sole downstream
consumer (`app.data.pipeline.stormwater.derive_tmdl_assets_from_ceden`)
filters to those plus a TMDL/WQIP keyword match, so the broader population
is dead weight.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import httpx


DEFAULT_RESOURCE_ID = "15a63495-8d9f-4a49-b43a-3092ef3106b9"
DEFAULT_OUTPUT = Path("data/raw/safetoswim_geomeans_2020-present.csv")
SQL_ENDPOINT = "https://data.ca.gov/api/3/action/datastore_search_sql"
PAGE_SIZE = 5000
MAX_PAGES = 400  # 2M-row safety cap; current dataset is ~550K matching rows
COLUMNS = [
    "Program",
    "ParentProject",
    "Project",
    "StationName",
    "StationCode",
    "SampleDate",
    "CollectionTime",
    "MethodName",
    "Analyte",
    "Unit",
    "Result",
    "ResultSub",
    "DataSource",
    "TargetLatitude",
    "TargetLongitude",
    "SampleComments",
    "CollectionComments",
    "ResultsComments",
    "SampleID",
    "SampleDateTime",
]
BACTERIA_FILTER = (
    "LOWER(\"Analyte\") LIKE '%enterococcus%' "
    "OR LOWER(\"Analyte\") LIKE '%coli%' "
    "OR LOWER(\"Analyte\") LIKE '%fecal%' "
    "OR LOWER(\"Analyte\") LIKE '%coliform%'"
)


def build_sql(resource_id: str, limit: int, offset: int) -> str:
    columns = ", ".join(f'"{c}"' for c in COLUMNS)
    return (
        f"SELECT {columns} FROM \"{resource_id}\" "
        f"WHERE {BACTERIA_FILTER} "
        f"ORDER BY \"_id\" "
        f"LIMIT {limit} OFFSET {offset}"
    )


def fetch_pages(
    resource_id: str,
    client: httpx.Client,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
):
    offset = 0
    for page in range(max_pages):
        sql = build_sql(resource_id, page_size, offset)
        for attempt in range(4):
            try:
                response = client.get(SQL_ENDPOINT, params={"sql": sql}, timeout=120.0)
                response.raise_for_status()
                break
            except (httpx.HTTPError, httpx.TransportError) as exc:
                if attempt == 3:
                    raise
                wait = 5 * (attempt + 1)
                print(f"[safetoswim] retry {attempt+1} after {wait}s ({exc})", file=sys.stderr)
                time.sleep(wait)
        records = response.json().get("result", {}).get("records", [])
        if not records:
            return
        yield records
        offset += len(records)
        if len(records) < page_size:
            return
    raise RuntimeError(f"hit max_pages={max_pages} without exhausting the dataset")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-id", default=DEFAULT_RESOURCE_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        help="No-op if output file already present (mirrors the old curl guard).",
    )
    args = parser.parse_args()

    if args.skip_if_exists and args.output.exists():
        print(f"[safetoswim] {args.output} already present; skipping fetch")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = args.output.with_suffix(args.output.suffix + ".tmp")

    total = 0
    with httpx.Client(follow_redirects=True) as client, tmp_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for batch in fetch_pages(args.resource_id, client, page_size=args.page_size):
            writer.writerows(batch)
            total += len(batch)
            print(f"[safetoswim] wrote {total} rows", flush=True)

    if total == 0:
        tmp_path.unlink(missing_ok=True)
        print("[safetoswim] datastore returned 0 rows; refusing to overwrite output", file=sys.stderr)
        return 1

    tmp_path.replace(args.output)
    print(f"[safetoswim] {total} rows -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
