"""The AI triage client: Azure OpenAI turns redacted symptom text into a validated TriageResult.

Keyless: authenticates with Microsoft Entra ID through DefaultAzureCredential (workload identity
on AKS, `az login` on a laptop). The Azure OpenAI resource has key auth turned off.
Never log the prompt, the reply or exceptions that may echo them: only metadata.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from app.models import TriageResult, Urgency
from app.parsing import parse_llm_output
from app.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("triage.ai")

CONTENT_FILTER_RESULT = TriageResult(
    urgency=Urgency.URGENT,
    suggested_specialty="General Practice",
    red_flags=["AI safety filter blocked this message"],
    summary=(
        "Automatic triage was blocked by the AI safety filter, which often means self-harm or "
        "violence is mentioned. Review this intake now."
    ),
)


def _is_content_filter(exc: Exception) -> bool:
    body = getattr(exc, "body", None)
    return isinstance(body, dict) and body.get("code") == "content_filter"


API_VERSION = "2025-04-01-preview"  # needed for gpt-5 reasoning models


@dataclass
class ClientReply:
    """A triage client's answer plus what the appointment service records about the call."""

    result: TriageResult
    tokens_used: int | None = None
    fallback_reason: str | None = None  # None = the model's answer was valid


@dataclass
class ModelReply:
    text: str
    tokens_used: int | None


# (system prompt, user prompt) -> raw model text + token count. Injected so tests need no cloud.
Generate = Callable[[str, str], ModelReply]


def is_reasoning_model(deployment: str) -> bool:
    """gpt-5* and o* models reason before answering and take different parameters."""
    name = deployment.lower()
    return name.startswith("gpt-5") or (name.startswith("o") and name[1:2].isdigit())


def chat_options(deployment: str) -> dict:
    """Request options that keep answers short, cheap and as repeatable as the model allows."""
    if is_reasoning_model(deployment):
        # No temperature for reasoning models; the token budget also covers their reasoning
        return {"max_completion_tokens": 2000, "reasoning_effort": "low"}
    return {"max_tokens": 512, "temperature": 0}


def azure_openai_generate(endpoint: str, deployment: str) -> Generate:
    """Build the real Azure OpenAI call. Imported lazily so the fake client needs no SDK setup."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=API_VERSION,
        timeout=20,
        max_retries=2,
    )

    def generate(system_prompt: str, user_prompt: str) -> ModelReply:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            **chat_options(deployment),
        )
        usage = response.usage
        return ModelReply(
            text=response.choices[0].message.content or "",
            tokens_used=usage.total_tokens if usage else None,
        )

    return generate


class AITriageClient:
    def __init__(self, generate: Generate):
        self._generate = generate

    @classmethod
    def from_env(cls) -> "AITriageClient":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("TRIAGE_CLIENT=azure-openai needs AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini").strip()
        return cls(azure_openai_generate(endpoint, deployment))

    def triage(self, redacted_text: str) -> ClientReply:
        try:
            reply = self._generate(SYSTEM_PROMPT, build_user_prompt(redacted_text))
        except Exception as exc:  # network, quota, auth, content filter: never fail the intake
            if _is_content_filter(exc):
                # The safety filter refuses text about self-harm or violence: exactly the
                # messages a clinician must see first. Never let that look like "soon".
                logger.warning("AI call blocked by the content filter, using urgent fallback")
                return ClientReply(CONTENT_FILTER_RESULT, None, "content_filter")
            logger.warning("AI call failed (%s), using fallback", type(exc).__name__)
            return ClientReply(parse_llm_output("").result, None, "model_error")
        outcome = parse_llm_output(reply.text)
        if outcome.is_fallback:
            logger.warning("AI reply rejected (%s), using fallback", outcome.fallback_reason)
        return ClientReply(outcome.result, reply.tokens_used, outcome.fallback_reason)
