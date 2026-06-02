import pandas as pd
import pytest

from app.data.pipeline.surf_spots import apply_surf_aliases, load_surf_aliases


@pytest.fixture
def beaches():
    # Three beaches: one right at Black's, one near Windansea, one far away (Oregon).
    return pd.DataFrame(
        {
            "beach_id": ["b-blacks", "b-windansea", "b-oregon"],
            "name": ["12345", "Neptune Pl drain", "Cannon Beach"],
            "latitude": [32.8896, 32.8331, 45.8918],
            "longitude": [-117.2519, -117.2792, -123.9615],
        }
    )


def test_assigns_surf_name_to_nearest_beach(beaches):
    aliases = pd.DataFrame(
        {
            "surf_name": ["Black's Beach"],
            "latitude": [32.8895],
            "longitude": [-117.2520],
        }
    )
    out = apply_surf_aliases(beaches, aliases=aliases, max_match_km=5.0)
    blacks = out.loc[out["beach_id"] == "b-blacks"].iloc[0]
    assert blacks["surf_name"] == "Black's Beach"
    assert bool(blacks["is_surf_spot"]) is True


def test_far_beach_is_not_a_surf_spot(beaches):
    aliases = pd.DataFrame(
        {"surf_name": ["Black's Beach"], "latitude": [32.8895], "longitude": [-117.2520]}
    )
    out = apply_surf_aliases(beaches, aliases=aliases, max_match_km=5.0)
    oregon = out.loc[out["beach_id"] == "b-oregon"].iloc[0]
    assert bool(oregon["is_surf_spot"]) is False
    assert pd.isna(oregon["surf_name"])
    # Display coords fall back to the beach's own location when unmatched.
    assert oregon["surf_latitude"] == pytest.approx(45.8918)
    assert oregon["surf_longitude"] == pytest.approx(-123.9615)


def test_surf_coords_use_curated_break_location(beaches):
    # Beach's stored coord is slightly off; the curated break coord should win for display.
    aliases = pd.DataFrame(
        {"surf_name": ["Black's Beach"], "latitude": [32.8895], "longitude": [-117.2520]}
    )
    out = apply_surf_aliases(beaches, aliases=aliases, max_match_km=5.0)
    blacks = out.loc[out["beach_id"] == "b-blacks"].iloc[0]
    assert blacks["surf_latitude"] == pytest.approx(32.8895)
    assert blacks["surf_longitude"] == pytest.approx(-117.2520)
    # Official coordinate is preserved untouched.
    assert blacks["latitude"] == pytest.approx(32.8896)


def test_each_alias_attaches_to_only_one_beach():
    # Two beaches near one alias — only the closest is renamed.
    beaches = pd.DataFrame(
        {
            "beach_id": ["near", "farther"],
            "name": ["a", "b"],
            "latitude": [32.8895, 32.8950],
            "longitude": [-117.2520, -117.2590],
        }
    )
    aliases = pd.DataFrame(
        {"surf_name": ["Black's Beach"], "latitude": [32.8895], "longitude": [-117.2520]}
    )
    out = apply_surf_aliases(beaches, aliases=aliases, max_match_km=5.0)
    assert out.loc[out["beach_id"] == "near", "is_surf_spot"].iloc[0]
    assert not out.loc[out["beach_id"] == "farther", "is_surf_spot"].iloc[0]


def test_curated_csv_loads_and_blacks_matches_torrey_pines():
    aliases = load_surf_aliases()
    assert "Black's Beach" in set(aliases["surf_name"])
    assert len(aliases) >= 30
    # A beach near Torrey Pines should pick up the Black's alias from the real CSV.
    beaches = pd.DataFrame(
        {
            "beach_id": ["tp"],
            "name": ["Torrey Pines State Beach"],
            "latitude": [32.8910],
            "longitude": [-117.2530],
        }
    )
    out = apply_surf_aliases(beaches)
    assert out.iloc[0]["surf_name"] == "Black's Beach"
