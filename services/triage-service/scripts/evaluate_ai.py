"""Run the 15 synthetic cases in tests/cases.json through the real Azure OpenAI model.

Needs `az login` (an account with the "Cognitive Services OpenAI User" role) and the endpoint
from `terraform output`. Each case goes through the same path as production: redact, then the
model, then validation.

    cd services/triage-service
    AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/ python scripts/evaluate_ai.py

Prints one line per case and a summary. An "urgent" case scored lower is the failure that
matters most (see docs/triage.md), so it is reported separately. Costs a few cents.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai_client import AITriageClient  # noqa: E402
from app.red_flags import find_red_flags  # noqa: E402
from app.redaction import redact  # noqa: E402

ORDER = {"routine": 0, "soon": 1, "urgent": 2}


def main() -> int:
    cases = json.loads((Path(__file__).parent.parent / "tests" / "cases.json").read_text("utf-8"))
    client = AITriageClient.from_env()
    correct = under_triaged = fallbacks = tokens = 0
    for case in cases:
        text = redact(case["symptoms"]).text
        reply = client.triage(text)
        ai_urgency = reply.result.urgency.value
        # Same as the endpoint: a red-flag rule makes it urgent, whatever the AI said
        got = "urgent" if find_red_flags(text) else ai_urgency
        expected = case["expected_urgency"]
        correct += got == expected
        fallbacks += reply.fallback_reason is not None
        tokens += reply.tokens_used or 0
        missed_urgent = expected == "urgent" and got != "urgent"
        under_triaged += missed_urgent
        mark = "ok " if got == expected else ("!!!" if missed_urgent else "-- ")
        note = reply.fallback_reason or ""
        if got != ai_urgency:
            note = f"{note} (AI said {ai_urgency}; raised by a red-flag rule)".strip()
        print(f"{mark} {case['id']:<24} expected {expected:<8} got {got:<8} {note}")
    n = len(cases)
    print(
        f"\n{correct}/{n} exact, {under_triaged} urgent case(s) under-triaged, "
        f"{fallbacks} fallback(s), {tokens} tokens"
    )
    return 1 if under_triaged else 0


if __name__ == "__main__":
    sys.exit(main())
