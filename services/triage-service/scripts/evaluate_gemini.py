"""Run the 15 synthetic cases in tests/cases.json through the real Gemini model.

Needs Vertex AI access: GCP_PROJECT_ID set and `gcloud auth application-default login`.
Each case goes through the same path as production: redact, then Gemini, then validation.

    cd services/triage-service
    GCP_PROJECT_ID=your-project python scripts/evaluate_gemini.py

Prints one line per case and a summary. An "urgent" case scored lower is the failure that
matters most (see docs/triage.md), so it is reported separately. Costs a few cents.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gemini_client import GeminiTriageClient  # noqa: E402
from app.redaction import redact  # noqa: E402

ORDER = {"routine": 0, "soon": 1, "urgent": 2}


def main() -> int:
    cases = json.loads((Path(__file__).parent.parent / "tests" / "cases.json").read_text("utf-8"))
    client = GeminiTriageClient.from_env()
    correct = under_triaged = fallbacks = tokens = 0
    for case in cases:
        reply = client.triage(redact(case["symptoms"]).text)
        got, expected = reply.result.urgency.value, case["expected_urgency"]
        correct += got == expected
        fallbacks += reply.fallback_reason is not None
        tokens += reply.tokens_used or 0
        missed_urgent = expected == "urgent" and got != "urgent"
        under_triaged += missed_urgent
        mark = "ok " if got == expected else ("!!!" if missed_urgent else "-- ")
        note = reply.fallback_reason or ""
        print(f"{mark} {case['id']:<24} expected {expected:<8} got {got:<8} {note}")
    n = len(cases)
    print(
        f"\n{correct}/{n} exact, {under_triaged} urgent case(s) under-triaged, "
        f"{fallbacks} fallback(s), {tokens} tokens"
    )
    return 1 if under_triaged else 0


if __name__ == "__main__":
    sys.exit(main())
