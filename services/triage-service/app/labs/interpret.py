"""Lab report pipeline: extract rows -> normalize units -> rule flags -> AI summary -> urgency."""

import logging
import time

from pydantic import BaseModel

from app import metrics
from app.labs.extract import Extractor
from app.labs.normalize import normalize
from app.labs.rules import flag, higher, lab_urgency
from app.labs.summary import template_summary
from app.models import Urgency

logger = logging.getLogger("triage.labs")


class LabResultOut(BaseModel):
    test_name: str
    display_name: str
    canonical: str | None
    value: float | None
    unit: str
    ref_low: float | None
    ref_high: float | None
    flag: str
    confidence: float | None
    needs_verification: bool
    verification_reason: str | None


class LabInterpretation(BaseModel):
    status: str  # ready | needs_review
    results: list[LabResultOut]
    rule_urgency: Urgency
    urgency: Urgency  # higher of rules and AI; the AI can raise, never lower
    reason: str
    clinician_summary: str
    patient_explanation: str
    extraction_confidence: float | None
    tokens_used: int | None
    fallback: bool


def interpret(
    content: bytes, content_type: str, extractor: Extractor, summarizer
) -> LabInterpretation:
    started = time.perf_counter()
    raw = extractor.extract(content, content_type)
    flagged = [
        flag(normalize(r.test_name, r.value_text, r.unit, r.ref_text), r.confidence) for r in raw
    ]
    rule_urgency, reason = lab_urgency(flagged)

    reply = summarizer.summarize(flagged)
    summary = reply.summary or template_summary(flagged, reason)
    urgency = higher(rule_urgency, summary.urgency.value)

    confidences = [r.confidence for r in flagged if r.confidence is not None]
    needs_review = not flagged or any(r.needs_verification for r in flagged)

    for r in flagged:
        metrics.LAB_RESULTS.labels(r.flag).inc()
    metrics.LAB_REPORTS.labels("needs_review" if needs_review else "ready", urgency).inc()
    if confidences:
        metrics.LAB_CONFIDENCE.observe(min(confidences))
    if reply.tokens_used:
        metrics.LLM_TOKENS.inc(reply.tokens_used)
    elapsed = time.perf_counter() - started
    metrics.LAB_SECONDS.observe(elapsed)
    # Metadata only: never test values or report text
    logger.info(
        "lab done results=%d urgency=%s rule_urgency=%s needs_review=%s fallback=%s duration_ms=%d",
        len(flagged),
        urgency,
        rule_urgency,
        needs_review,
        reply.fallback_reason or "no",
        elapsed * 1000,
    )
    return LabInterpretation(
        status="needs_review" if needs_review else "ready",
        results=[
            LabResultOut(
                test_name=r.measurement.test_name,
                display_name=r.measurement.display_name,
                canonical=r.measurement.canonical,
                value=r.measurement.value,
                unit=r.measurement.unit,
                ref_low=r.measurement.ref_low,
                ref_high=r.measurement.ref_high,
                flag=r.flag,
                confidence=r.confidence,
                needs_verification=r.needs_verification,
                verification_reason=r.verification_reason,
            )
            for r in flagged
        ],
        rule_urgency=rule_urgency,
        urgency=urgency,
        reason=reason,
        clinician_summary=summary.clinician_summary,
        patient_explanation=summary.patient_explanation,
        extraction_confidence=min(confidences) if confidences else None,
        tokens_used=reply.tokens_used,
        fallback=reply.summary is None,
    )
