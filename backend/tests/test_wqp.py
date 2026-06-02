import pandas as pd

from app.data.pipeline.wqp import normalize_wqp_results


def _wqx_frame():
    return pd.DataFrame(
        [
            # culture (MPN) enterococcus, above the 104 STV
            {
                "MonitoringLocationIdentifier": "FL_DEP-WQX-21FLBRDW-BIDB1",
                "CharacteristicName": "Enterococcus",
                "ResultMeasureValue": "200",
                "ResultMeasure/MeasureUnitCode": "MPN/100mL",
                "ResultAnalyticalMethod/MethodName": "Enterolert",
                "ActivityStartDate": "2026-05-10",
                "ActivityLocation/LatitudeMeasure": "26.12",
                "ActivityLocation/LongitudeMeasure": "-80.10",
            },
            # ddPCR (copies) enterococcus, below the molecular 1413 threshold
            {
                "MonitoringLocationIdentifier": "FL_DEP-WQX-21FLBRDW-BIDB2",
                "CharacteristicName": "Enterococcus",
                "ResultMeasureValue": "500",
                "ResultMeasure/MeasureUnitCode": "copies/100mL",
                "ResultAnalyticalMethod/MethodName": "ddPCR",
                "ActivityStartDate": "2026-05-11",
                "ActivityLocation/LatitudeMeasure": "26.13",
                "ActivityLocation/LongitudeMeasure": "-80.11",
            },
            # a different analyte — must be dropped
            {
                "MonitoringLocationIdentifier": "X",
                "CharacteristicName": "Nitrate",
                "ResultMeasureValue": "5",
                "ResultMeasure/MeasureUnitCode": "mg/L",
                "ResultAnalyticalMethod/MethodName": "EPA 300.0",
                "ActivityStartDate": "2026-05-10",
                "ActivityLocation/LatitudeMeasure": "26.0",
                "ActivityLocation/LongitudeMeasure": "-80.0",
            },
            # invalid negative value — must be dropped
            {
                "MonitoringLocationIdentifier": "Y",
                "CharacteristicName": "Enterococcus",
                "ResultMeasureValue": "-999",
                "ResultMeasure/MeasureUnitCode": "MPN/100mL",
                "ResultAnalyticalMethod/MethodName": "Enterolert",
                "ActivityStartDate": "2026-05-10",
                "ActivityLocation/LatitudeMeasure": "26.0",
                "ActivityLocation/LongitudeMeasure": "-80.0",
            },
        ]
    )


def test_keeps_only_valid_enterococcus_rows():
    out = normalize_wqp_results(_wqx_frame(), stv_threshold=104.0)
    assert set(out["station_id"]) == {
        "FL_DEP-WQX-21FLBRDW-BIDB1",
        "FL_DEP-WQX-21FLBRDW-BIDB2",
    }
    assert (out["analyte"] == "enterococcus").all()


def test_method_aware_exceedance():
    out = normalize_wqp_results(_wqx_frame(), stv_threshold=104.0).set_index("station_id")
    # culture 200 > 104 -> exceeds; ddPCR 500 <= 1413 -> not
    assert bool(out.loc["FL_DEP-WQX-21FLBRDW-BIDB1", "exceeds_stv"]) is True
    assert bool(out.loc["FL_DEP-WQX-21FLBRDW-BIDB2", "exceeds_stv"]) is False


def test_parses_value_units_method_coords_date():
    out = normalize_wqp_results(_wqx_frame(), stv_threshold=104.0).set_index("station_id")
    r = out.loc["FL_DEP-WQX-21FLBRDW-BIDB1"]
    assert r["value"] == 200.0
    assert r["units"] == "MPN/100mL"
    assert r["method"] == "Enterolert"
    assert round(r["latitude"], 2) == 26.12
    assert round(r["longitude"], 2) == -80.10
    assert str(pd.to_datetime(r["sample_time"]).date()) == "2026-05-10"
    assert r["data_source"] == "WQP"


def test_empty_input_returns_empty_with_schema():
    out = normalize_wqp_results(pd.DataFrame(), stv_threshold=104.0)
    assert out.empty
    assert "exceeds_stv" in out.columns and "station_id" in out.columns
