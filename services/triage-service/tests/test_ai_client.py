"""AITriageClient with the model call replaced by a fake, so no cloud access is needed."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.ai_client import AITriageClient, ClientReply, ModelReply, chat_options
from app.models import Urgency
from app.parsing import FALLBACK_URGENCY

VALID = {
    "urgency": "urgent",
    "suggested_specialty": "Cardiology",
    "red_flags": ["chest pain on exertion"],
    "summary": "Chest pain when climbing stairs since yesterday.",
}


class FakeModel:
    def __init__(self, text="", tokens=321, error: Exception | None = None):
        self.text, self.tokens, self.error = text, tokens, error
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str) -> ModelReply:
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return ModelReply(self.text, self.tokens)


def test_valid_json_becomes_a_result_with_token_count():
    model = FakeModel(json.dumps(VALID))
    reply = AITriageClient(model).triage("<PERSON> has chest pain")
    assert reply.result.urgency == Urgency.URGENT
    assert reply.tokens_used == 321
    assert reply.fallback_reason is None
    system, user = model.calls[0]
    assert "decision support" in system
    assert "<PERSON> has chest pain" in user


def test_json_in_code_fences_is_accepted():
    reply = AITriageClient(FakeModel(f"```json\n{json.dumps(VALID)}\n```")).triage("x")
    assert reply.fallback_reason is None


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("I think this is urgent", "invalid_json"),
        (json.dumps(VALID | {"diagnosis": "angina"}), "schema_error"),
        (json.dumps(VALID | {"urgency": "whenever"}), "schema_error"),
    ],
    ids=["prose", "extra-field", "bad-urgency"],
)
def test_bad_model_output_falls_back_safely(text, reason):
    reply = AITriageClient(FakeModel(text)).triage("x")
    assert reply.fallback_reason == reason
    assert reply.result.urgency == FALLBACK_URGENCY
    assert "manually" in reply.result.summary


def test_model_errors_fall_back_and_do_not_leak_details(caplog):
    error = RuntimeError("quota exceeded for text: my chest hurts")
    with caplog.at_level(logging.DEBUG):
        reply = AITriageClient(FakeModel(error=error)).triage("my chest hurts")
    assert reply.fallback_reason == "model_error"
    assert reply.tokens_used is None
    assert "RuntimeError" in caplog.text
    assert "chest" not in caplog.text


def test_endpoint_reports_tokens_and_fallback(monkeypatch):
    monkeypatch.setattr(main, "client", AITriageClient(FakeModel(json.dumps(VALID), tokens=99)))
    body = TestClient(main.app).post("/triage", json={"symptoms": "chest pain"}).json()
    assert body["urgency"] == "urgent" and body["tokens_used"] == 99 and body["fallback"] is False

    monkeypatch.setattr(main, "client", AITriageClient(FakeModel("nonsense")))
    body = TestClient(main.app).post("/triage", json={"symptoms": "sore knee for a week"}).json()
    assert body["urgency"] == FALLBACK_URGENCY and body["fallback"] is True


def test_simple_clients_still_work_through_the_endpoint():
    # FakeTriageClient returns a bare TriageResult; the endpoint wraps it
    body = TestClient(main.app).post("/triage", json={"symptoms": "mild cough"}).json()
    assert body["fallback"] is False and body["tokens_used"] is None
    assert isinstance(ClientReply, type)


@pytest.mark.parametrize("deployment", ["gpt-5-mini", "o4-mini", "GPT-5"])
def test_reasoning_models_get_a_reasoning_budget_and_no_temperature(deployment):
    options = chat_options(deployment)
    assert "temperature" not in options and "max_tokens" not in options
    assert options["max_completion_tokens"] >= 1000
    assert options["reasoning_effort"] == "low"


@pytest.mark.parametrize("deployment", ["gpt-4.1-mini", "gpt-4o-mini", "open-model"])
def test_chat_models_are_deterministic_and_short(deployment):
    assert chat_options(deployment) == {"max_tokens": 512, "temperature": 0}
