"""Generate the synthetic lab report PDFs in docs/samples/ (for demos and tests).

Everything in them is invented. Run from the repo root (needs `pip install reportlab`, which is
only used here, not by the services):

    python services/triage-service/scripts/make_sample_lab_reports.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[3] / "docs" / "samples"

REPORTS = {
    "lab-report-normal.pdf": [
        ("Sodium", "139", "mmol/L", "135 - 145", ""),
        ("Potassium", "4.2", "mmol/L", "3.5 - 5.1", ""),
        ("Glucose, fasting", "92", "mg/dL", "70 - 99", ""),
        ("Hemoglobin", "13.8", "g/dL", "12.0 - 16.0", ""),
        ("Platelets", "250", "10^9/L", "150 - 400", ""),
    ],
    "lab-report-critical-potassium.pdf": [
        ("Sodium", "136", "mmol/L", "135 - 145", ""),
        ("Potassium", "6.8", "mmol/L", "3.5 - 5.1", "H"),
        ("Creatinine", "1.9", "mg/dL", "0.6 - 1.2", "H"),
        ("Glucose, fasting", "97", "mg/dL", "70 - 99", ""),
        ("Hemoglobin", "12.9", "g/dL", "12.0 - 16.0", ""),
    ],
    "lab-report-high-glucose-mmol.pdf": [
        ("Glucose, fasting", "11.2", "mmol/L", "3.9 - 5.5", "H"),
        ("HbA1c", "8.1", "%", "4.0 - 5.6", "H"),
        ("Hemoglobin", "128", "g/L", "120 - 160", ""),
        ("Total cholesterol", "5.9", "mmol/L", "< 5.2", "H"),
        ("TSH", "2.1", "mIU/L", "0.4 - 4.0", ""),
    ],
}


def build(name: str, rows: list[tuple[str, ...]]) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT / name), pagesize=letter, title="Synthetic lab report")
    table = Table([("Test", "Result", "Units", "Reference range", "Flag"), *rows])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    doc.build(
        [
            Paragraph("Example Community Lab", styles["Title"]),
            Paragraph(
                "SYNTHETIC REPORT - not a real patient - for a course project", styles["Normal"]
            ),
            Spacer(1, 8),
            Paragraph("Patient name: Jane Example", styles["Normal"]),
            Paragraph("DOB: 1990-01-01", styles["Normal"]),
            Paragraph("MRN: 0000123", styles["Normal"]),
            Paragraph("Collected: 2026-10-30 08:15", styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for file_name, rows in REPORTS.items():
        build(file_name, rows)
        print("wrote", OUT / file_name)
