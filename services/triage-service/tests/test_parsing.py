import json

import pytest

from app.models import Urgency
from app.parsing import FALLBACK_URGENCY, parse_llm_output

VALID = {
    "urgency": "urgent",
    "suggested_specialty": "Emergency Medicine",
    "red_flags": ["chest pain"],
    "summary": "Possible cardiac event.",
}


def test_valid_json_is_accepted():
    outcome = parse_llm_output(json.dumps(VALID))
    assert not outcome.is_fallback
    assert outcome.result.urgency == Urgency.URGENT
    assert outcome.result.red_flags == ["chest pain"]


def test_json_wrapped_in_code_fence_is_accepted():
    outcome = parse_llm_output("```json\n" + json.dumps(VALID) + "\n```")
    assert not outcome.is_fallback


def test_missing_red_flags_defaults_to_empty_list():
    data = {k: v for k, v in VALID.items() if k != "red_flags"}
    outcome = parse_llm_output(json.dumps(data))
    assert not outcome.is_fallback
    assert outcome.result.red_flags == []


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param(json.dumps({**VALID, "urgency": "critical"}), 
                     "schema_error", 
                     id="bad-urgency"),
        pytest.param(
            json.dumps({k: v for k, v in VALID.items() if k != "summary"}),
            "schema_error",
            id="missing-summary",
        ),
        pytest.param(json.dumps({**VALID, "diagnosis": "flu"}), "schema_error", id="extra-field"),
        pytest.param("I think this is urgent.", "invalid_json", id="not-json"),
        pytest.param("", "invalid_json", id="empty"),
    ],
)
def test_bad_output_returns_a_safe_fallback(raw, reason):
    outcome = parse_llm_output(raw)
    assert outcome.is_fallback
    assert outcome.fallback_reason == reason
    assert outcome.result.urgency == FALLBACK_URGENCY
    assert "manually" in outcome.result.summary


def test_fallback_is_never_routine():
    assert FALLBACK_URGENCY != Urgency.ROUTINE


def test_fallback_does_not_echo_the_bad_output():
    outcome = parse_llm_output("Patient Jane Doe, 555-123-4567")
    assert "Jane" not in outcome.result.summary
    assert "Jane" not in (outcome.fallback_reason or "")