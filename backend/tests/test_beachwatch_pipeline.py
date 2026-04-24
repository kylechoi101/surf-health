import pandas as pd

from app.data.pipeline.beachwatch import (
    build_beach_day_frame,
    normalize_advisories,
    normalize_bacteria_results,
    normalize_station_metadata,
)


def test_beachwatch_normalization_filters_to_marine_enterococcus():
    stations = pd.DataFrame(
        [
            {
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "CountyName": "Orange",
                "Regional Board Name": "Santa Ana",
                "Status": "Active",
                "Station_UpperLat": "33.5",
                "Station_UpperLon": "-117.8",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
                "USEPAID": "CA123",
                "Agency_Name": "County Lab",
            }
        ]
    )
    normalized_stations = normalize_station_metadata(stations)
    assert len(normalized_stations) == 1
    assert normalized_stations.iloc[0]["support_status"] == "production"

    results = pd.DataFrame(
        [
            {
                "Parameter": "Enterococcus",
                "SampleDate": "4/18/2026",
                "StartTime": "08:00:00",
                "Result": "120",
                "Unit": "CFU/100ml",
                "AnalysisMethod": "Culture",
                "CountyName": "Orange",
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "USEPAID": "CA123",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
                "Weather": "Sunny",
                "StormDrainFlow": "No",
                "TidalHeight": "1.2",
                "SurfHeight": "2",
                "Turbidity": "5",
                "Odor": "None",
                "WaterColor": "Blue",
            },
            {
                "Parameter": "E. Coli",
                "SampleDate": "4/18/2026",
                "StartTime": "08:00:00",
                "Result": "120",
                "Unit": "CFU/100ml",
                "AnalysisMethod": "Culture",
                "CountyName": "Orange",
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "USEPAID": "CA123",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
            },
        ]
    )
    normalized_results = normalize_bacteria_results(results, stv_threshold=104.0)
    assert len(normalized_results) == 1
    assert normalized_results.iloc[0]["analyte"] == "enterococcus"
    assert bool(normalized_results.iloc[0]["exceeds_stv"]) is True


def test_beachwatch_normalization_filters_implausible_legacy_dates():
    results = pd.DataFrame(
        [
            {
                "Parameter": "Enterococcus",
                "SampleDate": "1/6/1900",
                "StartTime": "09:31:00",
                "Result": "120",
                "Unit": "CFU/100ml",
                "AnalysisMethod": "Culture",
                "CountyName": "Orange",
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "USEPAID": "CA123",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
            },
            {
                "Parameter": "Enterococcus",
                "SampleDate": "4/18/2026",
                "StartTime": "08:00:00",
                "Result": "95",
                "Unit": "CFU/100ml",
                "AnalysisMethod": "Culture",
                "CountyName": "Orange",
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "USEPAID": "CA123",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
            },
        ]
    )

    normalized_results = normalize_bacteria_results(results, stv_threshold=104.0)

    assert len(normalized_results) == 1
    assert str(normalized_results.iloc[0]["sample_date"]) == "2026-04-18"


def test_beachwatch_bundle_builds_beach_day_and_advisories():
    observations = pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "sample_time": pd.Timestamp("2026-04-18T08:00:00"),
                "sample_date": pd.Timestamp("2026-04-18").date(),
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": 120.0,
                "exceeds_stv": True,
                "county": "Orange",
                "station_name": "Main Beach Pier",
                "beach_name": "Main Beach",
                "usepa_id": "CA123",
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.2,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
                "odor": "None",
                "water_color": "Blue",
            }
        ]
    )
    stations = pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "name": "Main Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": pd.Timestamp("2026-04-18T08:00:00"),
                "latitude": 33.5,
                "longitude": -117.8,
                "usepa_id": "CA123",
                "water_body_class": "Saltwater",
                "water_body_type": "Open Coast",
                "agency_name": "County Lab",
            }
        ]
    )
    advisories_raw = pd.DataFrame(
        [
            {
                "DateOpened": "4/18/2026",
                "TimeOpened": "10:30:00",
                "DateofAdvisory": "4/18/2026",
                "TimeofAdvisory": "10:00:00",
                "AdvisoryType": "Posting",
                "AdvisoryCause": "Unknown Cause",
                "CountyName": "Orange",
                "Station_Name": "Main Beach Pier",
                "Beach_Name": "Main Beach",
                "USEPAID": "CA123",
                "WaterBodyClass": "Saltwater",
                "WaterBodyType": "Open Coast",
            }
        ]
    )
    advisories = normalize_advisories(advisories_raw)
    beach_day = build_beach_day_frame(observations, stations, advisories)
    assert len(advisories) == 1
    assert len(beach_day) == 1
    assert beach_day.iloc[0]["historical_advisory_count"] == 1
    assert beach_day.iloc[0]["enterococcus_value"] == 120.0
