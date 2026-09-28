import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verify_served_estimate as v  # noqa: E402

from app.ml.logit_challenger import LOGIT_CHALLENGER_VERSION  # noqa: E402
from app.ml.lookup_serving import LOOKUP_MODEL_VERSION  # noqa: E402


def test_the_script_names_the_version_the_serving_module_writes():
    # The script is run standalone in CI, so it hardcodes the string.
    assert v.LOGIT_VERSION == LOGIT_CHALLENGER_VERSION


@pytest.mark.parametrize(
    "block, ok",
    [
        ({"name": LOGIT_CHALLENGER_VERSION, "method_requested": "logit", "fallback_reason": None}, True),
        ({"name": LOOKUP_MODEL_VERSION, "method_requested": "lookup", "fallback_reason": None}, True),
        ({"name": LOOKUP_MODEL_VERSION, "method_requested": "logit", "fallback_reason": "KeyError: 'W'"}, False),
        (None, False),
    ],
)
def test_resolve(block, ok):
    payload = {} if block is None else {"serving_method": block}
    passed, message = v.resolve(payload)
    assert passed is ok
    if block and not ok:
        assert "KeyError" in message


def test_main_exit_codes(tmp_path, monkeypatch):
    health = tmp_path / "system_health.json"
    health.write_text(json.dumps({"serving_method": {"name": LOOKUP_MODEL_VERSION, "method_requested": "logit",
                                                     "fallback_reason": "boom"}}))
    monkeypatch.setattr(sys, "argv", ["x", "--curated", str(tmp_path)])
    assert v.main() == 1
    health.write_text(json.dumps({"serving_method": {"name": LOGIT_CHALLENGER_VERSION, "method_requested": "logit"}}))
    assert v.main() == 0
