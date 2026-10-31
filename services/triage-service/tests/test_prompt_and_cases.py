"""Checks for the Gemini prompt and the synthetic evaluation cases (tests/cases.json).

The cases are for evaluating the real model later. Here we only check they are well formed.
"""

import json
from collections import Counter
from pathlib import Path

from app.models import Urgency
from app.prompts import SYSTEM_PROMPT, build_user_prompt
from app.redaction import redact

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


def test_prompt_states_decision_support_and_lists_every_field():
    assert "decision support" in SYSTEM_PROMPT
    assert "do not diagnose" in SYSTEM_PROMPT.lower()
    for field in ("urgency", "suggested_specialty", "red_flags", "summary"):
        assert f'"{field}"' in SYSTEM_PROMPT  # from the generated JSON Schema
    for level in Urgency:
        assert f'"{level}"' in SYSTEM_PROMPT


def test_user_prompt_wraps_the_text():
    assert build_user_prompt("  sore throat ").endswith("<<<\nsore throat\n>>>")


def test_there_are_15_unique_cases_covering_every_urgency():
    assert len(CASES) == 15
    assert len({case["id"] for case in CASES}) == 15
    counts = Counter(case["expected_urgency"] for case in CASES)
    assert set(counts) == {u.value for u in Urgency}
    assert min(counts.values()) >= 4


def test_cases_have_the_expected_fields():
    for case in CASES:
        assert set(case) == {"id", "symptoms", "expected_urgency", "notes"}
        assert case["symptoms"].strip()


def test_redaction_leaves_the_clinical_part_of_the_pii_case():
    [case] = [c for c in CASES if c["id"] == "pii-with-chest-pain"]
    text = redact(case["symptoms"]).text
    assert "Jane" not in text and "555-123-4567" not in text
    assert "chest pain" in text
