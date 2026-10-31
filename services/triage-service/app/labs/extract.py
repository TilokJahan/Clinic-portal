"""Read lab rows (test, value, unit, reference range) out of an uploaded report.

Two extractors, chosen by LAB_EXTRACTOR:
- "text" (default, local and CI): text-based PDFs through pypdf. Photos can't be read: the report
  is then sent for manual review.
- "azure-document-intelligence" (cloud): Azure AI Document Intelligence, prebuilt-layout model,
  for PDFs and photos. Keyless (DefaultAzureCredential: workload identity on AKS).
Both return the same RawRow list, with an OCR confidence where the extractor has one.
"""

import io
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("triage.labs")

PDF = "application/pdf"
IMAGES = {"image/png", "image/jpeg"}


@dataclass
class RawRow:
    test_name: str
    value_text: str
    unit: str
    ref_text: str
    confidence: float | None = None


class Extractor(Protocol):
    def extract(self, content: bytes, content_type: str) -> list[RawRow]: ...


# One result per line, e.g. "Potassium   6.8   mmol/L   3.5 - 5.1   H"
_LINE = re.compile(
    r"^\s*(?P<test>[A-Za-z][A-Za-z0-9 ,()/+\-]*?)\s*:?\s+"
    r"(?P<value>[<>]?\s?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>(?:x?10\^\d+/[a-zA-Zµ]+|[a-zA-Zµ%][a-zA-Zµ%/0-9.^]*)?)\s*"
    r"(?:(?:ref(?:erence)?(?: range)?:?)\s*)?"
    r"(?P<ref>(?:[<>≤≥]=?\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?))?"
    r"\s*(?:[HLhl*!]{1,2}|high|low|critical)?\s*$",
    re.IGNORECASE,
)
_SKIP = re.compile(r"\b(date|dob|born|mrn|patient|name|phone|page|collected|reported)\b", re.I)


def parse_lines(lines: Iterable[str], confidences: dict[int, float] | None = None) -> list[RawRow]:
    """Lines that look like 'test value unit range'. Header/demographic lines are skipped."""
    rows = []
    for i, line in enumerate(lines):
        if _SKIP.search(line):
            continue
        match = _LINE.match(line)
        if match and match.group("test").strip().lower() not in ("test", "analyte", "result"):
            rows.append(
                RawRow(
                    test_name=match.group("test").strip(" ,:"),
                    value_text=match.group("value").replace(" ", ""),
                    unit=(match.group("unit") or "").strip(),
                    ref_text=(match.group("ref") or "").strip(),
                    confidence=(confidences or {}).get(i),
                )
            )
    return rows


HEADER_WORDS = {
    "test": ("test", "analyte", "component", "name", "investigation"),
    "value": ("result", "value", "your value"),
    "unit": ("unit", "units"),
    "ref": ("reference", "range", "ref", "normal"),
}


def rows_from_table(
    cells: list[list[str]], confidences: list[list[float | None]] | None = None
) -> list[RawRow]:
    """A table with a header row naming the columns (test / result / unit / reference)."""
    if len(cells) < 2:
        return []
    header = [c.strip().lower() for c in cells[0]]
    cols: dict[str, int] = {}
    for key, words in HEADER_WORDS.items():
        for idx, title in enumerate(header):
            if idx not in cols.values() and any(w in title for w in words):
                cols[key] = idx
                break
    if "test" not in cols or "value" not in cols:
        return []
    rows = []
    for r, row in enumerate(cells[1:], start=1):

        def cell(key: str, row: list[str] = row) -> str:
            idx = cols.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        if not cell("test") or not re.search(r"\d", cell("value")):
            continue
        unit = cell("unit")
        value = cell("value")
        if not unit:  # "6.8 mmol/L" in one cell
            split = re.match(r"^([<>]?\s?\d+(?:[.,]\d+)?)\s*(.*)$", value)
            if split:
                value, unit = split.group(1), split.group(2)
        conf = [c for c in (confidences[r] if confidences else []) if c is not None]
        rows.append(RawRow(cell("test"), value, unit, cell("ref"), min(conf) if conf else None))
    return rows


class TextExtractor:
    """Text PDFs only (pypdf). Good for synthetic reports and CI; no OCR."""

    def extract(self, content: bytes, content_type: str) -> list[RawRow]:
        if content_type != PDF:
            return []  # photos need OCR: the report goes to manual review
        from pypdf import PdfReader

        pages = PdfReader(io.BytesIO(content)).pages
        # Layout mode keeps each table row on one line, the way it looks on the page
        text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in pages)
        return parse_lines(text.splitlines())


class AzureDocumentIntelligenceExtractor:
    """Azure AI Document Intelligence, prebuilt-layout: tables first, then text lines."""

    def __init__(self, endpoint: str, client=None):
        if client is None:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.identity import DefaultAzureCredential

            client = DocumentIntelligenceClient(endpoint, DefaultAzureCredential())
        self._client = client

    def extract(self, content: bytes, content_type: str) -> list[RawRow]:
        poller = self._client.begin_analyze_document(
            "prebuilt-layout", body=content, content_type="application/octet-stream"
        )
        result = poller.result()
        words = [w for page in (result.pages or []) for w in (page.words or [])]

        def confidence_of(spans) -> float | None:
            values = []
            for span in spans or []:
                end = span.offset + span.length
                values += [w.confidence for w in words if span.offset <= w.span.offset < end]
            return min(values) if values else None

        rows: list[RawRow] = []
        for table in result.tables or []:
            grid = [[""] * table.column_count for _ in range(table.row_count)]
            conf: list[list[float | None]] = [
                [None] * table.column_count for _ in range(table.row_count)
            ]
            for c in table.cells:
                grid[c.row_index][c.column_index] = c.content or ""
                conf[c.row_index][c.column_index] = confidence_of(c.spans)
            rows += rows_from_table(grid, conf)
        if rows:
            return rows
        lines = [ln for page in (result.pages or []) for ln in (page.lines or [])]
        confidences = {i: confidence_of(ln.spans) for i, ln in enumerate(lines)}
        return parse_lines([ln.content for ln in lines], confidences)


def get_extractor() -> Extractor:
    name = os.getenv("LAB_EXTRACTOR", "text").strip().lower()
    if name == "text":
        return TextExtractor()
    if name == "azure-document-intelligence":
        endpoint = os.getenv("DOCINTEL_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("LAB_EXTRACTOR=azure-document-intelligence needs DOCINTEL_ENDPOINT")
        return AzureDocumentIntelligenceExtractor(endpoint)
    raise ValueError(
        f"Unknown LAB_EXTRACTOR {name!r}. Use 'text' or 'azure-document-intelligence'."
    )
