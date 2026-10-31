"""Gemini on Vertex AI: turns redacted symptom text into a validated TriageResult.

Auth uses Application Default Credentials: Workload Identity on AKS/GKE, or
`gcloud auth application-default login` on a laptop. No API keys in code or config.
Never log the prompt, the reply or exceptions that may echo them: only metadata.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from app.models import TriageResult
from app.parsing import parse_llm_output
from app.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("triage.gemini")

DEFAULT_MODEL = "gemini-2.5-flash"


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


def vertex_generate(project: str, location: str, model: str) -> Generate:
    """Build the real Vertex AI call. Imported lazily so the fake client needs no SDK setup."""
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project, location=location)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.0,  # same input, same answer: easier to test and to audit
        max_output_tokens=512,
    )

    def generate(system_prompt: str, user_prompt: str) -> ModelReply:
        response = client.models.generate_content(model=model, contents=user_prompt, config=config)
        usage = response.usage_metadata
        return ModelReply(
            text=response.text or "", tokens_used=usage.total_token_count if usage else None
        )

    return generate


class GeminiTriageClient:
    def __init__(self, generate: Generate):
        self._generate = generate

    @classmethod
    def from_env(cls) -> "GeminiTriageClient":
        project = os.getenv("GCP_PROJECT_ID", "").strip()
        if not project:
            raise ValueError("TRIAGE_CLIENT=gemini needs GCP_PROJECT_ID")
        location = os.getenv("GCP_REGION", "us-central1").strip()
        model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip()
        return cls(vertex_generate(project, location, model))

    def triage(self, redacted_text: str) -> ClientReply:
        try:
            reply = self._generate(SYSTEM_PROMPT, build_user_prompt(redacted_text))
        except Exception as exc:  # network, quota, auth, safety block: never fail the intake
            logger.warning("gemini call failed (%s), using fallback", type(exc).__name__)
            outcome = parse_llm_output("")
            return ClientReply(outcome.result, None, "model_error")
        outcome = parse_llm_output(reply.text)
        if outcome.is_fallback:
            logger.warning("gemini reply rejected (%s), using fallback", outcome.fallback_reason)
        return ClientReply(outcome.result, reply.tokens_used, outcome.fallback_reason)
