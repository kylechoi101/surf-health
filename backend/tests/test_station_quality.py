import pandas as pd

from app.data.pipeline.station_quality import (
    MIN_SAMPLING_SPAN_DAYS,
    support_status_for,
)


def test_min_span_is_90_days():
    assert MIN_SAMPLING_SPAN_DAYS == 90


def test_one_time_station_single_day_is_unsupported():
    # 1 sample, span 0 days — classic one-time incident.
    assert support_status_for(observation_count=1, sampling_span_days=0) == "unsupported"


def test_short_span_overrides_count():
    # Even with many samples, a <90-day total history is incident-response noise.
    assert support_status_for(observation_count=25, sampling_span_days=14) == "unsupported"


def test_span_below_threshold_is_unsupported():
    assert support_status_for(observation_count=5, sampling_span_days=89) == "unsupported"


def test_span_at_threshold_is_supported():
    # Exactly 90 days is NOT capped (threshold is "< 90").
    assert support_status_for(observation_count=5, sampling_span_days=90) == "beta"


def test_long_history_few_samples_is_beta():
    assert support_status_for(observation_count=4, sampling_span_days=400) == "beta"


def test_long_history_many_samples_is_production():
    assert support_status_for(observation_count=20, sampling_span_days=400) == "production"


def test_missing_span_is_unsupported():
    assert support_status_for(observation_count=3, sampling_span_days=None) == "unsupported"
    assert support_status_for(observation_count=3, sampling_span_days=float("nan")) == "unsupported"
