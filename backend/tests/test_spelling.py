import pandas as pd

from app.data.pipeline.spelling import correct_place_spelling, SPELLING_CORRECTIONS


def test_fixes_tijuana():
    assert correct_place_spelling("Tijana River") == "Tijuana River"


def test_fixes_oceanside():
    assert correct_place_spelling("Oceanisde Blvd") == "Oceanside Blvd"


def test_fixes_storm_drain():
    assert (
        correct_place_spelling("Temescal Canyon storn drain on Will Rogers Beach")
        == "Temescal Canyon storm drain on Will Rogers Beach"
    )


def test_fixes_outlet():
    assert correct_place_spelling("Loma Alta Creek oultet") == "Loma Alta Creek outlet"


def test_is_case_insensitive_but_keeps_canonical_form():
    assert correct_place_spelling("TIJANA RIVER") == "Tijuana RIVER"


def test_leaves_correct_and_intentional_spellings_untouched():
    # Already-correct words and intentional Spanish ("Cañon") must not change.
    assert correct_place_spelling("Oceanside Pier") == "Oceanside Pier"
    assert correct_place_spelling("Boca del Canon Beach") == "Boca del Canon Beach"


def test_only_whole_words_replaced():
    # Must not corrupt a longer word that merely contains a typo token.
    assert correct_place_spelling("Storndale Cove") == "Storndale Cove"


def test_handles_nan_and_none():
    assert correct_place_spelling(None) is None
    assert pd.isna(correct_place_spelling(float("nan")))


def test_corrections_table_is_lowercase_keyed():
    assert all(k == k.lower() for k in SPELLING_CORRECTIONS)
