"""Fixed red-flag rules on symptom text, and the content-filter fallback."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.ai_client import AITriageClient
from app.models import TriageResult, Urgency
from app.red_flags import find_red_flags

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("last night I started thinking about ending my life", "possible self-harm risk"),
        ("I have been having suicidal thoughts", "possible self-harm risk"),
        ("crushing pressure in my chest for 30 minutes", "chest pain or pressure"),
        ("I can't catch my breath even sitting still", "trouble breathing"),
        ("his face looks droopy on one side and his speech is slurred", "possible stroke signs"),
        ("she passed out in the kitchen", "loss of consciousness"),
        ("my throat is swelling after a bee sting", "possible anaphylaxis"),
        ("worst headache of my life", "sudden severe headache"),
    ],
)
def test_red_flags_are_found(text, label):
    assert label in find_red_flags(text)


@pytest.mark.parametrize(
    "text",
    [
        "Runny nose and a scratchy throat for two days",
        "Need a refill of my blood pressure tablets",
        "Twisted my ankle playing football",
        "Itchy eyes every spring",
    ],
)
def test_ordinary_symptoms_have_no_red_flags(text):
    assert find_red_flags(text) == []


def test_every_urgent_evaluation_case_except_the_vague_ones_is_caught_by_rules_or_ai():
    # The rules alone catch every "urgent" case in tests/cases.json, so even with the AI down or
    # filtered, no urgent case is under-triaged
    urgent = [c for c in CASES if c["expected_urgency"] == "urgent"]
    assert all(find_red_flags(c["symptoms"]) for c in urgent)
    routine = [c for c in CASES if c["expected_urgency"] == "routine"]
    assert not any(find_red_flags(c["symptoms"]) for c in routine)


class SoonClient:
    def triage(self, text):
        return TriageResult(urgency=Urgency.SOON, suggested_specialty="GP", summary="s")


def test_a_rule_raises_the_ai_result_to_urgent(monkeypatch):
    monkeypatch.setattr(main, "client", SoonClient())
    body = (
        TestClient(main.app)
        .post("/triage", json={"symptoms": "I keep thinking about killing myself"})
        .json()
    )
    assert body["urgency"] == "urgent"
    assert body["red_flags"][0] == "possible self-harm risk"


def test_no_rule_keeps_the_ai_result(monkeypatch):
    monkeypatch.setattr(main, "client", SoonClient())
    body = TestClient(main.app).post("/triage", json={"symptoms": "ear pain for four days"}).json()
    assert body["urgency"] == "soon"


class FilterError(Exception):
    body = {"code": "content_filter", "innererror": {"code": "ResponsibleAIPolicyViolation"}}


def test_content_filter_refusal_falls_back_to_urgent():
    def blocked(system, user):
        raise FilterError("blocked")

    reply = AITriageClient(blocked).triage("text the filter refuses")
    assert reply.result.urgency == Urgency.URGENT
    assert reply.fallback_reason == "content_filter"
    assert "Review this intake now" in reply.result.summary


def test_other_ai_errors_keep_the_soon_fallback():
    def broken(system, user):
        raise RuntimeError("network")

    reply = AITriageClient(broken).triage("x")
    assert reply.result.urgency == Urgency.SOON and reply.fallback_reason == "model_error"
