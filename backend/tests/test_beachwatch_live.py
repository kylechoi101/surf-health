"""Live-BeachWatch source: parsing, normalization, and additive merge."""

from __future__ import annotations

import pandas as pd

from app.data.connectors.beachwatch_live import COUNTY_CODES, parse_results_html
from app.data.pipeline.beachwatch_live import (
    DATA_SOURCE,
    merge_live_into_observations,
    normalize_live_results,
)


def _row(station, date, param, result, unit, method, county="San Diego", beach="Test Beach"):
    return (
        "<tr>\n"
        f'<td class="tab-data">{station}</td>\n'
        f'<td class="tab-data">{date}</td>\n'
        '<td class="tab-data">07:30:00</td>\n'
        f'<td class="tab-data">{param}</td>\n'
        '<td class="tab-data" align="center">=</td>\n'
        f'<td class="tab-data">{result}</td>\n'
        f'<td class="tab-data">{unit}</td>\n'
        f'<td class="tab-data" align="center">{method}</td>\n'
        f'<td class="tab-data" align="center">{county}</td>\n'
        '<td class="tab-data">Somewhere</td>\n'
        '<td class="tab-data">32.6</td>\n'
        '<td class="tab-data">-117.1</td>\n'
        f'<td class="tab-data">{beach}</td>\n'
        "</tr>"
    )


def _stations():
    return pd.DataFrame(
        [
            {"beach_id": "b-alpha", "station_code": "IB-079", "usepa_id": "CA1", "county": "San Diego"},
            {"beach_id": "b-beta", "station_code": "EH-050", "usepa_id": "CA2", "county": "San Diego"},
        ]
    )


def test_parse_results_html_extracts_the_thirteen_columns():
    markup = "<table>" + _row("IB-079", "2026-07-26", "Enterococcus", "1504", "Copies/100ml", "MCB-ddPCR") + "</table>"
    frame = parse_results_html(markup)
    assert len(frame) == 1
    assert frame.iloc[0]["station_code"] == "IB-079"
    assert frame.iloc[0]["sample_date"] == "2026-07-26"
    assert frame.iloc[0]["result"] == "1504"
    assert frame.iloc[0]["unit"] == "Copies/100ml"


def test_ddpcr_uses_the_molecular_threshold_not_the_culture_stv():
    """San Diego reports Copies/100ml; 1504 exceeds (>1413) and 1268 does not.

    Judged against the 104 culture STV both would flag — that flat threshold
    false-flagged ~98% of PCR samples before the 2026-06-01 correction.
    """
    markup = (
        _row("IB-079", "2026-07-26", "Enterococcus", "1504", "Copies/100ml", "MCB-ddPCR")
        + _row("EH-050", "2026-07-26", "Enterococcus", "1268", "Copies/100ml", "MCB-ddPCR")
    )
    live = normalize_live_results(parse_results_html(markup), _stations(), 104.0,
                                  now=pd.Timestamp("2026-07-29"))
    by_beach = live.set_index("beach_id")["exceeds_stv"]
    assert bool(by_beach["b-alpha"]) is True
    assert bool(by_beach["b-beta"]) is False


def test_normalize_drops_future_dated_and_unmappable_rows():
    markup = (
        _row("IB-079", "2026-07-26", "Enterococcus", "50", "MPN/100ml", "Enterolert")
        + _row("IB-079", "2026-10-02", "Enterococcus", "50", "MPN/100ml", "Enterolert")  # future
        + _row("NOPE-999", "2026-07-26", "Enterococcus", "50", "MPN/100ml", "Enterolert")  # unmapped
        + _row("IB-079", "2026-07-26", "Total Coliforms", "50", "MPN/100ml", "Enterolert")  # not entero
    )
    live = normalize_live_results(parse_results_html(markup), _stations(), 104.0,
                                  now=pd.Timestamp("2026-07-29"))
    assert len(live) == 1
    assert live.iloc[0]["beach_id"] == "b-alpha"
    assert live.iloc[0]["data_source"] == DATA_SOURCE


def test_merge_is_additive_and_existing_sources_win():
    """A live mirror of a row we already hold must not displace it, and a genuinely
    new sample must be added — that asymmetry is the whole design."""
    existing = pd.DataFrame(
        [
            {
                "beach_id": "b-alpha", "sample_time": pd.Timestamp("2026-07-20 07:30:00"),
                "sample_date": pd.Timestamp("2026-07-20").date(), "analyte": "enterococcus",
                "method": "Enterolert", "units": "MPN/100ml", "value": 50.0,
                "exceeds_stv": False, "county": "San Diego", "station_name": "IB-079",
                "beach_name": "Test Beach", "usepa_id": "CA1", "data_source": "BeachWatch",
                "station_code": "IB-079",
            }
        ]
    )
    markup = (
        _row("IB-079", "2026-07-20", "Enterococcus", "50", "MPN/100ml", "Enterolert")   # mirror
        + _row("IB-079", "2026-07-26", "Enterococcus", "80", "MPN/100ml", "Enterolert")  # new
    )
    live = normalize_live_results(parse_results_html(markup), _stations(), 104.0,
                                  now=pd.Timestamp("2026-07-29"))
    live.loc[live["sample_time"] == pd.Timestamp("2026-07-20 07:30:00"), "sample_time"] = pd.Timestamp("2026-07-20 07:30:00")
    merged = merge_live_into_observations(existing, live)

    assert len(merged) == 2, "mirror should collapse, new sample should be added"
    kept = merged.loc[merged["sample_time"] == pd.Timestamp("2026-07-20 07:30:00")]
    assert kept.iloc[0]["data_source"] == "BeachWatch", "existing source must win the mirror"
    added = merged.loc[merged["sample_time"] == pd.Timestamp("2026-07-26 07:30:00")]
    assert added.iloc[0]["data_source"] == DATA_SOURCE


def test_county_codes_cover_the_live_form():
    assert COUNTY_CODES["San Diego"] == 10
    assert COUNTY_CODES["Los Angeles"] == 5
    assert len(COUNTY_CODES) == 16
