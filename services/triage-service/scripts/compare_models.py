import time

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "US_SSN"]

# (sentence, must be removed, must survive)
CASES = [
    ("My name is Jane Doe and I have a headache", ["Jane Doe"], ["headache"]),
    ("Call me at 555-123-4567 about my cough", ["555-123-4567"], ["cough"]),
    ("Email me at jane.doe@example.com, my knee hurts", ["jane.doe@example.com"], ["knee"]),
    ("Chest pain for two days", [], ["Chest pain", "two days"]),
    ("I take 500 mg twice a day for back pain", [], ["500 mg", "twice a day", "back pain"]),
    ("Dr. Patel saw me in Detroit last week", ["Patel", "Detroit"], ["last week"]),
    ("this is maria gonzalez, dizzy since monday", ["maria gonzalez"], ["dizzy"]),
    ("My son Liam has a fever of 102", ["Liam"], ["fever", "102"]),
    ("Raj Patel here, rash on my arm", ["Raj Patel"], ["rash"]),
    ("SSN 678-00-1939, short of breath", ["678-00-1939"], ["short of breath"]),
]


def build_analyzer(model_name: str) -> AnalyzerEngine:
    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": model_name}],
        }
    ).create_engine()
    return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])


def evaluate(model_name: str) -> None:
    start = time.perf_counter()
    analyzer = build_analyzer(model_name)
    load_seconds = time.perf_counter() - start
    anonymizer = AnonymizerEngine()

    print(f"\n=== {model_name} (load time {load_seconds:.1f}s) ===")
    total_leaks = total_lost = 0
    run_start = time.perf_counter()
    for text, must_remove, must_keep in CASES:
        found = analyzer.analyze(text=text, language="en", entities=ENTITIES)
        out = anonymizer.anonymize(text=text, analyzer_results=found).text
        leaked = [s for s in must_remove if s.lower() in out.lower()]
        lost = [s for s in must_keep if s.lower() not in out.lower()]
        total_leaks += len(leaked)
        total_lost += len(lost)
        print(f"{'OK  ' if not leaked and not lost else 'FAIL'} {out}")
        if leaked:
            print(f"     LEAKED (private text still present): {leaked}")
        if lost:
            print(f"     LOST (useful text removed):          {lost}")
    ms_per_call = (time.perf_counter() - run_start) / len(CASES) * 1000
    print(f"--> leaks: {total_leaks}, wrongly removed: {total_lost}, ~{ms_per_call:.0f} ms/call")


if __name__ == "__main__":
    for model in ("en_core_web_sm", "en_core_web_lg"):
        evaluate(model)