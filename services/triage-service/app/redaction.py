import re
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

# Entities to remove. DATE_TIME is deliberately NOT here (see step 5).
ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "US_SSN"]


@dataclass
class RedactionResult:
    text: str
    entities: list[str]  # entity TYPES found, never the original values


_nlp = NlpEngineProvider(
    nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp, supported_languages=["en"])
_anonymizer = AnonymizerEngine()


## fallback to catch SSNs that Presidio misses. 
## This is a known gap in the model comparison (scripts/compare_models.py).
_SSN_FALLBACK = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

def redact(text: str) -> RedactionResult:
    found = _analyzer.analyze(text=text, language="en", entities=ENTITIES)
    result = _anonymizer.anonymize(text=text, analyzer_results=found)
    entities = {r.entity_type for r in found}

    # Second pass: catch anything Presidio left behind
    cleaned, count = _SSN_FALLBACK.subn("<US_SSN>", result.text)
    if count:
        entities.add("US_SSN")

    return RedactionResult(text=cleaned, entities=sorted(entities))