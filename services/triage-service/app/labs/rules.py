"""Fixed rules for lab flags and lab urgency. The AI never decides these.

Critical thresholds are common adult panic values (synthetic-data course project, not clinical
guidance). They apply only when the test and unit are recognized (canonical units below).
"""

from dataclasses import dataclass

from app.labs.normalize import Measurement

# canonical key -> (critical below, critical above), in the canonical unit from normalize.TESTS
CRITICAL: dict[str, tuple[float | None, float | None]] = {
    "potassium": (2.5, 6.0),  # mmol/L
    "sodium": (120, 160),  # mmol/L
    "glucose": (54, 400),  # mg/dL
    "hemoglobin": (7.0, None),  # g/dL
    "platelets": (20, 1000),  # 10^9/L
    "wbc": (2.0, 30.0),  # 10^9/L
    "creatinine": (None, 5.0),  # mg/dL
    "calcium": (6.0, 13.0),  # mg/dL
    "inr": (None, 5.0),
}

# Values outside these are almost certainly OCR mistakes (e.g. 68 instead of 6.8): verify by hand
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "potassium": (1.0, 12.0),
    "sodium": (90, 200),
    "glucose": (10, 2000),
    "hemoglobin": (2, 25),
    "platelets": (1, 3000),
    "wbc": (0.1, 200),
    "creatinine": (0.1, 30),
    "calcium": (2, 20),
    "inr": (0.5, 15),
}

MIN_CONFIDENCE = 0.8
URGENCY_ORDER = {"routine": 0, "soon": 1, "urgent": 2}


@dataclass
class FlaggedResult:
    measurement: Measurement
    flag: str  # normal | low | high | critical_low | critical_high | unknown
    confidence: float | None
    needs_verification: bool
    verification_reason: str | None


def flag(m: Measurement, confidence: float | None = None) -> FlaggedResult:
    reason = None
    if m.value is None:
        reason = "no readable value"
    elif confidence is not None and confidence < MIN_CONFIDENCE:
        reason = f"low OCR confidence ({confidence:.0%})"
    elif m.canonical in PLAUSIBLE and m.unit_is_canonical():
        lo, hi = PLAUSIBLE[m.canonical]
        if not lo <= m.value <= hi:
            reason = "implausible value, check the report"

    if m.value is None:
        result = "unknown"
    else:
        result = "normal"
        crit_lo, crit_hi = (
            CRITICAL.get(m.canonical, (None, None)) if m.unit_is_canonical() else (None, None)
        )
        if crit_lo is not None and m.value < crit_lo:
            result = "critical_low"
        elif crit_hi is not None and m.value > crit_hi:
            result = "critical_high"
        elif m.ref_low is not None and m.value < m.ref_low:
            result = "low"
        elif m.ref_high is not None and m.value > m.ref_high:
            result = "high"
    return FlaggedResult(m, result, confidence, reason is not None, reason)


def describe(r: FlaggedResult) -> str:
    unit = f" {r.measurement.unit}" if r.measurement.unit else ""
    value = f"{r.measurement.value:g}" if r.measurement.value is not None else "?"
    return f"{r.measurement.display_name.lower()} {value}{unit}"


def lab_urgency(results: list[FlaggedResult]) -> tuple[str, str]:
    """(urgency, reason). Any critical value -> urgent; any abnormal -> soon; else routine."""
    critical = [r for r in results if r.flag.startswith("critical")]
    if critical:
        return "urgent", "Critical: " + ", ".join(describe(r) for r in critical)
    abnormal = [r for r in results if r.flag in ("low", "high")]
    if abnormal:
        label = "Abnormal: " + ", ".join(f"{describe(r)} ({r.flag})" for r in abnormal[:3])
        return "soon", label + ("…" if len(abnormal) > 3 else "")
    if not results:
        return "soon", "No results could be read: check the report by hand"
    if any(r.needs_verification for r in results):
        return "routine", "Results in range; some values need checking"
    return "routine", "All results within range"


def higher(a: str, b: str) -> str:
    return a if URGENCY_ORDER[a] >= URGENCY_ORDER[b] else b
