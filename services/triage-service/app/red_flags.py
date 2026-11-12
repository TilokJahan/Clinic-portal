"""Deterministic red-flag rules for symptom text, applied alongside the AI.

Found in the evaluation (docs/triage.md): Azure OpenAI's content filter refuses text about
self-harm, so the AI path fell back to "soon" for the case that most needs "urgent". Like the lab
critical values, these phrases make the result urgent no matter what the AI says; the AI can raise
urgency but never lower a rule result. Runs on the redacted text. Synthetic data, course project:
a safety net, not a clinical screening tool.
"""

import re

# label shown to the clinician -> patterns (case-insensitive)
RED_FLAGS: dict[str, list[str]] = {
    "possible self-harm risk": [
        r"\bsuicid",
        r"\bkill(ing)? myself\b",
        r"\bend(ing)? (my|it all|my own) li(fe|ves)\b",
        r"\bself[- ]?harm",
        r"\bhurt(ing)? myself\b",
        r"\bdon'?t want to (live|be alive)\b",
        r"\boverdos",
        r"\bno reason to live\b",
    ],
    "chest pain or pressure": [
        r"\bchest (pain|pressure|tightness)\b",
        r"\b(crushing|squeezing) (chest|pressure)\b",
        r"\bpressure in my chest\b",
        r"\bpain in my chest\b",
    ],
    "trouble breathing": [
        r"\bcan'?t (catch my )?breath",
        r"\bcannot breathe\b",
        r"\bcan'?t breathe\b",
        r"\bshort(ness)? of breath at rest\b",
        r"\blips? (look |are |turning )?blue\b",
        r"\bstruggling to breathe\b",
    ],
    "possible stroke signs": [
        r"\bface (is |looks )?(droop|drooping|droopy)\b",
        r"\b(droop|drooping|droopy) on one side\b",
        r"\bslurred speech\b",
        r"\bspeech is slurred\b",
        r"\bweakness on one side\b",
        r"\bsudden (numbness|weakness)\b",
    ],
    "loss of consciousness": [r"\bunconscious\b", r"\bpassed out\b", r"\bfaint(ed|ing)\b"],
    "severe bleeding": [
        r"\b(heavy|severe|won'?t stop) bleeding\b",
        r"\bbleeding (heavily|a lot)\b",
        r"\bvomiting blood\b",
        r"\bcoughing up blood\b",
    ],
    "possible anaphylaxis": [
        r"\b(throat|tongue) (is )?(swelling|swollen|closing)\b",
        r"\banaphyla",
    ],
    "sudden severe headache": [r"\bworst headache\b", r"\bthunderclap\b"],
}

_COMPILED = {
    label: [re.compile(p, re.I) for p in patterns] for label, patterns in RED_FLAGS.items()
}


def find_red_flags(text: str) -> list[str]:
    """Labels of the red flags mentioned in the text, in a stable order."""
    return [label for label, patterns in _COMPILED.items() if any(p.search(text) for p in patterns)]
