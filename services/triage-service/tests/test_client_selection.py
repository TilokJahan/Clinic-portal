import pytest

from app.triage_client import FakeTriageClient, get_client


def test_defaults_to_fake_when_unset(monkeypatch):
    monkeypatch.delenv("TRIAGE_CLIENT", raising=False)
    assert isinstance(get_client(), FakeTriageClient)


@pytest.mark.parametrize("value", ["fake", "FAKE", " fake "])
def test_fake_is_case_and_space_insensitive(monkeypatch, value):
    monkeypatch.setenv("TRIAGE_CLIENT", value)
    assert isinstance(get_client(), FakeTriageClient)


def test_gemini_needs_a_project(monkeypatch):
    monkeypatch.setenv("TRIAGE_CLIENT", "gemini")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        get_client()


def test_gemini_is_selected_with_a_project(monkeypatch):
    from app import gemini_client

    monkeypatch.setenv("TRIAGE_CLIENT", "gemini")
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    seen = {}

    def fake_vertex(project, location, model):
        seen.update(project=project, location=location, model=model)
        return lambda system, user: None

    monkeypatch.setattr(gemini_client, "vertex_generate", fake_vertex)
    assert isinstance(get_client(), gemini_client.GeminiTriageClient)
    assert seen == {"project": "demo-project", "location": "us-central1", "model": "gemini-test"}


def test_unknown_value_is_rejected(monkeypatch):
    monkeypatch.setenv("TRIAGE_CLIENT", "banana")
    with pytest.raises(ValueError, match="banana"):
        get_client()
