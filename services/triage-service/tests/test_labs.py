"""Lab report pipeline: parsing, unit conversion, rule flags, AI summary and the endpoint."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.ai_client import ModelReply
from app.labs.extract import (
    AzureDocumentIntelligenceExtractor,
    TextExtractor,
    parse_lines,
    rows_from_table,
)
from app.labs.interpret import interpret
from app.labs.normalize import normalize, parse_range
from app.labs.rules import flag, higher, lab_urgency
from app.labs.summary import AILabSummarizer, FakeLabSummarizer

SAMPLES = Path(__file__).resolve().parents[3] / "docs" / "samples"


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


# --- parsing ----------------------------------------------------------------------------------


def test_lines_are_parsed_and_patient_details_skipped():
    rows = parse_lines(
        [
            "Patient name: Jane Example",
            "DOB: 1990-01-01",
            "MRN: 0000123",
            "Test   Result  Units  Reference range",
            "Potassium   6.8   mmol/L   3.5 - 5.1   H",
            "Total cholesterol 5.9 mmol/L < 5.2 H",
            "HbA1c 8.1 % 4.0 - 5.6",
        ]
    )
    assert [(r.test_name, r.value_text, r.unit, r.ref_text) for r in rows] == [
        ("Potassium", "6.8", "mmol/L", "3.5 - 5.1"),
        ("Total cholesterol", "5.9", "mmol/L", "< 5.2"),
        ("HbA1c", "8.1", "%", "4.0 - 5.6"),
    ]


def test_table_with_header_row_and_value_and_unit_in_one_cell():
    rows = rows_from_table(
        [
            ["Analyte", "Your value", "Normal range"],
            ["Sodium", "141 mmol/L", "135-145"],
            ["Comment", "see below", ""],
        ],
        [[None] * 3, [0.99, 0.62, 0.97], [None] * 3],
    )
    assert len(rows) == 1
    assert (rows[0].value_text, rows[0].unit, rows[0].ref_text) == ("141", "mmol/L", "135-145")
    assert rows[0].confidence == 0.62  # the weakest cell in the row


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.5 - 5.1", (3.5, 5.1)),
        ("3,5–5,1", (3.5, 5.1)),
        ("< 200", (None, 200)),
        (">40", (40, None)),
        ("", (None, None)),
        ("negative", (None, None)),
    ],
)
def test_reference_ranges(text, expected):
    assert parse_range(text) == expected


# --- normalization and rules -------------------------------------------------------------------


def test_units_are_converted_to_canonical():
    glucose = normalize("Glucose, fasting", "11.2", "mmol/L", "3.9 - 5.5")
    assert (glucose.canonical, glucose.value, glucose.unit) == ("glucose", 201.8, "mg/dL")
    assert (glucose.ref_low, glucose.ref_high) == (70.3, 99.1)
    hb = normalize("Hgb", "128", "g/L", "120-160")
    assert (hb.value, hb.unit) == (12.8, "g/dL")


def test_unknown_tests_keep_their_units_and_use_the_report_range():
    m = normalize("Vitamin D", "15", "ng/mL", "30 - 100")
    assert (m.canonical, m.unit) == (None, "ng/mL")
    assert flag(m).flag == "low"


@pytest.mark.parametrize(
    ("test", "value", "unit", "ref", "expected"),
    [
        ("Potassium", "6.8", "mmol/L", "3.5-5.1", "critical_high"),
        ("Potassium", "2.3", "mmol/L", "3.5-5.1", "critical_low"),
        ("Potassium", "5.4", "mmol/L", "3.5-5.1", "high"),
        ("Glucose", "2.5", "mmol/L", "3.9-5.5", "critical_low"),  # 45 mg/dL after conversion
        ("Sodium", "139", "mmol/L", "135-145", "normal"),
        ("Hemoglobin", "65", "g/L", "120-160", "critical_low"),  # 6.5 g/dL
    ],
)
def test_rule_flags(test, value, unit, ref, expected):
    assert flag(normalize(test, value, unit, ref)).flag == expected


def test_critical_rules_need_a_recognized_unit():
    # Potassium in an unknown unit: no critical rule, only the report's own range
    m = normalize("Potassium", "6.8", "mg/dL", "3.5-5.1")
    assert flag(m).flag == "high"


@pytest.mark.parametrize(
    ("value", "confidence", "reason"),
    [("68", None, "implausible"), ("4.2", 0.55, "low OCR confidence"), ("?", None, "no readable")],
)
def test_values_needing_verification(value, confidence, reason):
    r = flag(normalize("Potassium", value, "mmol/L", "3.5-5.1"), confidence)
    assert r.needs_verification and reason in r.verification_reason


def test_lab_urgency_and_reason():
    critical = flag(normalize("Potassium", "6.8", "mmol/L", "3.5-5.1"))
    high = flag(normalize("Creatinine", "1.9", "mg/dL", "0.6-1.2"))
    normal = flag(normalize("Sodium", "139", "mmol/L", "135-145"))
    assert lab_urgency([critical, high, normal]) == ("urgent", "Critical: potassium 6.8 mmol/L")
    assert lab_urgency([high, normal])[0] == "soon"
    assert lab_urgency([normal]) == ("routine", "All results within range")
    assert lab_urgency([])[0] == "soon"  # nothing readable: a person must look


def test_higher_urgency():
    assert higher("routine", "urgent") == "urgent"
    assert higher("urgent", "routine") == "urgent"


# --- whole pipeline with the synthetic PDFs ---------------------------------------------------


def test_critical_potassium_report_is_urgent():
    out = interpret(
        sample("lab-report-critical-potassium.pdf"),
        "application/pdf",
        TextExtractor(),
        FakeLabSummarizer(),
    )
    assert out.urgency == "urgent" and out.rule_urgency == "urgent"
    assert out.reason == "Critical: potassium 6.8 mmol/L"
    assert out.status == "ready"
    assert {r.display_name: r.flag for r in out.results}["Creatinine"] == "high"
    assert "Jane" not in json.dumps(out.model_dump())  # report header never copied


def test_normal_report_is_routine():
    out = interpret(
        sample("lab-report-normal.pdf"), "application/pdf", TextExtractor(), FakeLabSummarizer()
    )
    assert (out.urgency, out.reason) == ("routine", "All results within range")
    assert len(out.results) == 5


def test_photos_need_ocr_and_go_to_review_without_it():
    out = interpret(b"\x89PNG fake", "image/png", TextExtractor(), FakeLabSummarizer())
    assert out.status == "needs_review" and out.results == []


# --- AI summary --------------------------------------------------------------------------------


class FakeModel:
    def __init__(self, text="", error=None):
        self.text, self.error, self.calls = text, error, []

    def __call__(self, system, user):
        self.calls.append(user)
        if self.error:
            raise self.error
        return ModelReply(self.text, 400)


def _flagged():
    return [
        flag(normalize("Potassium", "6.8", "mmol/L", "3.5-5.1")),
        flag(normalize("Sodium", "139", "mmol/L", "135-145")),
    ]


def test_ai_summary_sees_only_rows_and_cannot_lower_urgency():
    model = FakeModel(
        json.dumps(
            {
                "clinician_summary": "Potassium critically high at 6.8.",
                "patient_explanation": "One result was higher than usual. We will call you.",
                "urgency": "routine",  # wrong: the rules say urgent
            }
        )
    )
    out = interpret(
        sample("lab-report-critical-potassium.pdf"),
        "application/pdf",
        TextExtractor(),
        AILabSummarizer(model),
    )
    assert out.urgency == "urgent"  # the AI can't lower a rule result
    assert out.clinician_summary == "Potassium critically high at 6.8."
    assert out.tokens_used == 400 and out.fallback is False
    sent = model.calls[0]
    assert "Potassium" in sent and "Jane" not in sent and "0000123" not in sent


def test_ai_can_raise_urgency():
    model = FakeModel(
        json.dumps({"clinician_summary": "s", "patient_explanation": "p", "urgency": "soon"})
    )
    out = interpret(
        sample("lab-report-normal.pdf"), "application/pdf", TextExtractor(), AILabSummarizer(model)
    )
    assert (out.rule_urgency, out.urgency) == ("routine", "soon")


@pytest.mark.parametrize(
    "model",
    [
        FakeModel("not json"),
        FakeModel(json.dumps({"clinician_summary": "s"})),
        FakeModel(error=RuntimeError("quota: potassium 6.8")),
    ],
    ids=["prose", "missing-fields", "error"],
)
def test_ai_failure_falls_back_to_the_template(model, caplog):
    with caplog.at_level(logging.DEBUG):
        reply = AILabSummarizer(model).summarize(_flagged())
    assert reply.summary is None
    assert "6.8" not in caplog.text  # values never logged


# --- Azure Document Intelligence adapter (fake client, no cloud) ------------------------------


def _span(offset, length):
    return SimpleNamespace(offset=offset, length=length)


def test_azure_extractor_reads_tables_with_word_confidence():
    cells = [
        (0, 0, "Test", 0),
        (0, 1, "Result", 5),
        (0, 2, "Units", 12),
        (0, 3, "Reference range", 18),
        (1, 0, "Potassium", 34),
        (1, 1, "6.8", 44),
        (1, 2, "mmol/L", 48),
        (1, 3, "3.5 - 5.1", 55),
    ]
    table = SimpleNamespace(
        row_count=2,
        column_count=4,
        cells=[
            SimpleNamespace(row_index=r, column_index=c, content=t, spans=[_span(o, len(t))])
            for r, c, t, o in cells
        ],
    )
    words = [
        SimpleNamespace(span=_span(o, len(t)), confidence=0.6 if t == "6.8" else 0.99)
        for _, _, t, o in cells
    ]
    result = SimpleNamespace(tables=[table], pages=[SimpleNamespace(words=words, lines=[])])
    client = SimpleNamespace(
        begin_analyze_document=lambda *a, **k: SimpleNamespace(result=lambda: result)
    )
    rows = AzureDocumentIntelligenceExtractor("https://x", client=client).extract(
        b"%PDF", "application/pdf"
    )
    assert [(r.test_name, r.value_text, r.unit, r.ref_text) for r in rows] == [
        ("Potassium", "6.8", "mmol/L", "3.5 - 5.1")
    ]
    assert rows[0].confidence == 0.6
    assert flag(
        normalize(rows[0].test_name, rows[0].value_text, rows[0].unit, rows[0].ref_text),
        rows[0].confidence,
    ).needs_verification


# --- endpoint ---------------------------------------------------------------------------------


def test_interpret_endpoint():
    client = TestClient(main.app)
    response = client.post(
        "/labs/interpret",
        content=sample("lab-report-critical-potassium.pdf"),
        headers={"content-type": "application/pdf"},
    )
    assert response.status_code == 200
    assert response.json()["reason"] == "Critical: potassium 6.8 mmol/L"
    assert (
        client.post(
            "/labs/interpret", content=b"x", headers={"content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/labs/interpret", content=b"", headers={"content-type": "application/pdf"}
        ).status_code
        == 413
    )
    metrics = client.get("/metrics").text
    assert 'lab_results_total{flag="critical_high"}' in metrics
