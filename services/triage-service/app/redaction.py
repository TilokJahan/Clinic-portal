"""PII redaction for symptom text, applied BEFORE anything is sent to an AI model.

Pipeline: Presidio (with the spaCy en_core_web_sm model) finds names, phone numbers, emails,
locations and SSNs. A small regex pass then catches dashed SSNs that Presidio misses.
See docs/triage.md for the model choice and the known limits.
"""

import re
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

# Entity types to remove. DATE_TIME is deliberately NOT included: it would also remove
# clinically useful phrases such as "two days" or "since Tuesday".
ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "US_SSN"]

# Fallback for dashed SSNs (NNN-NN-NNNN). Presidio's built-in US_SSN recognizer missed one in
# our model comparison (scripts/compare_models.py). Undashed 9-digit numbers are not covered.
_SSN_FALLBACK = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass
class RedactionResult:
    text: str
    entities: list[str]  # entity TYPES found, never the original values


# Build the engines once at import time. Loading the model is slow, so never do it per request.
_nlp = NlpEngineProvider(
    nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp, supported_languages=["en"])
_anonymizer = AnonymizerEngine()


def redact(text: str) -> RedactionResult:
    """Replace private details with tokens such as <PERSON>. Never log the input text."""
    found = _analyzer.analyze(text=text, language="en", entities=ENTITIES)
    result = _anonymizer.anonymize(text=text, analyzer_results=found)
    entities = {r.entity_type for r in found}

    # Second pass: catch anything Presidio left behind.
    cleaned, count = _SSN_FALLBACK.subn("<US_SSN>", result.text)
    if count:
        entities.add("US_SSN")

    return RedactionResult(text=cleaned, entities=sorted(entities))