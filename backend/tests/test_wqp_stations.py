import pandas as pd

from app.data.pipeline.wqp import build_wqp_stations, COASTAL_STATE_FIPS


def _norm_obs():
    # two stations, station A sampled over >90d (supported), station B one-off
    rows = []
    for d in ["2025-01-01", "2025-03-01", "2025-06-01", "2025-09-01"]:
        rows.append({"station_id": "HI301H_WQX-C3A", "sample_time": pd.Timestamp(d),
                     "sample_date": pd.Timestamp(d).date(), "value": 30.0, "exceeds_stv": False,
                     "latitude": 21.30, "longitude": -157.85, "state_fips": "US:15"})
    rows.append({"station_id": "FL-ONE", "sample_time": pd.Timestamp("2025-05-01"),
                 "sample_date": pd.Timestamp("2025-05-01").date(), "value": 5.0, "exceeds_stv": False,
                 "latitude": 26.1, "longitude": -80.1, "state_fips": "US:12"})
    return pd.DataFrame(rows)


def test_coastal_states_list_is_reasonable():
    # ~30 coastal states/territories; FIPS format US:NN
    assert len(COASTAL_STATE_FIPS) >= 23
    assert all(s.startswith("US:") for s in COASTAL_STATE_FIPS)
    assert "US:06" in COASTAL_STATE_FIPS  # California


def test_one_station_row_per_station_with_coords():
    stations = build_wqp_stations(_norm_obs())
    assert set(stations["station_id"]) == {"HI301H_WQX-C3A", "FL-ONE"}
    a = stations.set_index("station_id").loc["HI301H_WQX-C3A"]
    assert round(a["latitude"], 2) == 21.30
    assert round(a["longitude"], 2) == -157.85


def test_beach_id_is_stable_unique_and_prefixed():
    stations = build_wqp_stations(_norm_obs())
    ids = stations["beach_id"].tolist()
    assert len(ids) == len(set(ids))                       # unique
    assert all(b.startswith("wqp-") for b in ids)          # namespaced, won't collide with CA ids
    # stable: rebuilding gives identical ids
    again = build_wqp_stations(_norm_obs())
    assert sorted(again["beach_id"]) == sorted(ids)


def test_duration_cap_marks_oneoff_stations_unsupported():
    stations = build_wqp_stations(_norm_obs()).set_index("station_id")
    # station A spans Jan->Sep (>90d, 4 samples) -> supported; FL-ONE single day -> unsupported
    assert stations.loc["HI301H_WQX-C3A", "support_status"] != "unsupported"
    assert stations.loc["FL-ONE", "support_status"] == "unsupported"


def test_empty_returns_empty():
    assert build_wqp_stations(pd.DataFrame()).empty
