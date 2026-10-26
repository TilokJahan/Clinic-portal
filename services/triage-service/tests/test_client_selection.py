import pytest

from app.triage_client import FakeTriageClient, get_client


def test_defaults_to_fake_when_unset(monkeypatch):
    monkeypatch.delenv("TRIAGE_CLIENT", raising=False)
    assert isinstance(get_client(), FakeTriageClient)


@pytest.mark.parametrize("value", ["fake", "FAKE", " fake "])
def test_fake_is_case_and_space_insensitive(monkeypatch, value):
    monkeypatch.setenv("TRIAGE_CLIENT", value)
    assert isinstance(get_client(), FakeTriageClient)


def test_gemini_is_not_available_yet(monkeypatch):
    monkeypatch.setenv("TRIAGE_CLIENT", "gemini")
    with pytest.raises(NotImplementedError):
        get_client()


def test_unknown_value_is_rejected(monkeypatch):
    monkeypatch.setenv("TRIAGE_CLIENT", "banana")
    with pytest.raises(ValueError, match="banana"):
        get_client()