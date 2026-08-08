"""Tests for ``dist_to_chronic_source_km`` (Step 6 plume-proximity geometry).

The feature is static beach geometry: distance to the nearest entry in
``_static_data/ca_chronic_sources.csv``. Two things need pinning and they are
different in kind.

*Behaviour* — the reduction is a nearest-source minimum, it degrades to NaN
rather than crashing when the source list is unavailable, and adding it did not
perturb the pier/estuary distances it now shares a loop with.

*Curation* — the file is deliberately single-source. The whole justification for
shipping this feature (see the CSV's ``evidence`` column and Step 6's report) is
that exactly one chronic source has a measured gradient in this dataset. Because
the reduction is a MINIMUM, one unevidenced row silently rewrites the feature's
value for every beach near it, with no schema change and no coverage change for
the diff harness to catch. So the curation is asserted, not assumed.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.data.pipeline.external_covariates import haversine_km
from app.data.pipeline.marine_microbiology import (
    _DEFAULT_CHRONIC_SOURCES_CSV,
    compute_beach_coastal_features,
)

# Tijuana River mouth, as carried by both ca_estuary_mouths.csv and
# ca_chronic_sources.csv. Deliberately the same coordinate in both files: it
# makes "nearest chronic source" and "nearest estuary mouth" differ by the
# CURATION and nothing else.
TIJUANA = (32.5466, -117.1290)


def _stations(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["beach_id", "latitude", "longitude"])


@pytest.fixture
def two_source_csv(tmp_path):
    path = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            {"name": "South", "latitude": 32.0, "longitude": -117.0, "county": "X"},
            {"name": "North", "latitude": 34.0, "longitude": -119.0, "county": "Y"},
        ]
    ).to_csv(path, index=False)
    return path


def test_column_is_distance_to_the_curated_source():
    # Imperial Beach Municipal, ~2.3 km up-coast of the river mouth.
    stations = _stations([("ib", 32.5666, -117.1330)])
    out = compute_beach_coastal_features(stations)
    expected = haversine_km(32.5666, -117.1330, *TIJUANA)
    assert out.loc[0, "dist_to_chronic_source_km"] == pytest.approx(expected)


def test_every_beach_gets_a_value_however_far_away():
    """100% coverage is an exit criterion, so 'far' must be a number, not NaN."""
    stations = _stations(
        [("ib", 32.5666, -117.1330), ("humboldt", 40.9385, -124.1100)]
    )
    out = compute_beach_coastal_features(stations)
    assert out["dist_to_chronic_source_km"].notna().all()
    far = out.set_index("beach_id").loc["humboldt", "dist_to_chronic_source_km"]
    assert far > 1000


def test_reduction_takes_the_nearest_source(two_source_csv):
    stations = _stations([("near_north", 33.9, -118.9), ("near_south", 32.1, -117.05)])
    out = compute_beach_coastal_features(
        stations, chronic_sources_csv=two_source_csv
    ).set_index("beach_id")
    assert out.loc["near_north", "dist_to_chronic_source_km"] == pytest.approx(
        haversine_km(33.9, -118.9, 34.0, -119.0)
    )
    assert out.loc["near_south", "dist_to_chronic_source_km"] == pytest.approx(
        haversine_km(32.1, -117.05, 32.0, -117.0)
    )


def test_missing_source_file_yields_nan_not_a_crash(tmp_path):
    """A connector-outage-shaped failure must degrade, matching pier/estuary."""
    out = compute_beach_coastal_features(
        _stations([("ib", 32.5666, -117.1330)]),
        chronic_sources_csv=tmp_path / "does_not_exist.csv",
    )
    assert out.loc[0, "dist_to_chronic_source_km"] != out.loc[0, "dist_to_chronic_source_km"]
    # ...and the siblings computed in the same loop are untouched.
    assert out.loc[0, "dist_to_pier_km"] > 0
    assert out.loc[0, "dist_to_estuary_km"] > 0


def test_chronic_source_is_not_the_estuary_list():
    """Dog Beach is the control that motivated a separate file.

    0.3 km from the San Diego River mouth (so ``dist_to_estuary_km`` is ~0) but
    26 km from the Tijuana plume, and it shows less than half Imperial Beach's
    assay-discordance rate. If the two columns ever agree here, the chronic list
    has been merged into the estuary list and the feature means nothing new.
    """
    out = compute_beach_coastal_features(_stations([("dog_beach", 32.7570, -117.2530)]))
    assert out.loc[0, "dist_to_estuary_km"] < 1.0
    assert out.loc[0, "dist_to_chronic_source_km"] > 20.0


def test_shipped_source_list_is_single_and_evidenced():
    sources = pd.read_csv(_DEFAULT_CHRONIC_SOURCES_CSV)
    assert list(sources["name"]) == ["Tijuana River Mouth"], (
        "ca_chronic_sources.csv gained a row. The feature is a MINIMUM over this "
        "file, so a new source changes dist_to_chronic_source_km for every beach "
        "near it without changing the schema or the coverage the diff harness "
        "checks. Add one only with a measured gradient, record it in the "
        "`evidence` column, and update this test deliberately."
    )
    assert sources["evidence"].str.len().min() > 50
    assert sources[["latitude", "longitude"]].notna().all().all()


def test_evidenced_coordinate_matches_the_estuary_entry():
    """Guards against the two files drifting to different Tijuana coordinates,
    which would silently turn a curation difference into a geometry difference.
    """
    estuaries = pd.read_csv(
        _DEFAULT_CHRONIC_SOURCES_CSV.parent / "ca_estuary_mouths.csv"
    )
    row = estuaries.loc[estuaries["name"] == "Tijuana River Mouth"].iloc[0]
    chronic = pd.read_csv(_DEFAULT_CHRONIC_SOURCES_CSV).iloc[0]
    assert (chronic["latitude"], chronic["longitude"]) == (
        row["latitude"],
        row["longitude"],
    )
