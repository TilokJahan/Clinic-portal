import pytest

from app.triage_client import FakeTriageClient, get_client


def test_defaults_to_fake_when_unset(monkeypatch):
    monkeypatch.delenv("TRIAGE_CLIENT", raising=False)
    assert isinstance(get_client(), FakeTriageClient)


@pytest.mark.parametrize("value", ["fake", "FAKE", " fake "])
def test_fake_is_case_and_space_insensitive(monkeypatch, value):
    monkeypatch.setenv("TRIAGE_CLIENT", value)
    assert isinstance(get_client(), FakeTriageClient)


def test_azure_openai_needs_an_endpoint(monkeypatch):
    monkeypatch.setenv("TRIAGE_CLIENT", "azure-openai")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        get_client()


def test_azure_openai_is_selected_with_an_endpoint(monkeypatch):
    from app import ai_client

    monkeypatch.setenv("TRIAGE_CLIENT", "azure-openai")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://demo.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
    seen = {}

    def fake_build(endpoint, deployment):
        seen.update(endpoint=endpoint, deployment=deployment)
        return lambda system, user: None

    monkeypatch.setattr(ai_client, "azure_openai_generate", fake_build)
    assert isinstance(get_client(), ai_client.AITriageClient)
    assert seen == {"endpoint": "https://demo.openai.azure.com/", "deployment": "gpt-test"}
