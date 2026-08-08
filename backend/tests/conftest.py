from __future__ import annotations

import pandas as pd
import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def beach_day_frame() -> pd.DataFrame:
    """The shipped label frame, for tests that must re-derive a property from
    real data rather than a fixture. Skips when it is absent (fresh clone / CI
    without curated data) so these never fail for the wrong reason."""
    path = Path(__file__).resolve().parents[2] / "data" / "curated" / "beach_day.parquet"
    if not path.exists():
        pytest.skip("data/curated/beach_day.parquet not present")
    return pd.read_parquet(path)
