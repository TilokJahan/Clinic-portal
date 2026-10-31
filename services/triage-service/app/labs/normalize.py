"""Turn raw lab rows (as printed on a report) into canonical tests, values and units.

The mapping table is deliberately small: the common tests a primary-care clinic sees, with their
aliases and unit conversions. Anything not in the table is kept as-is (no conversion, no critical
rule) and still gets a high/low flag from the report's own reference range.
"""

import re
from dataclasses import dataclass

# canonical key -> display name, canonical unit, {unit alias (lowercase): factor to canonical}
TESTS: dict[str, tuple[str, str, dict[str, float]]] = {
    "potassium": ("Potassium", "mmol/L", {"mmol/l": 1, "meq/l": 1}),
    "sodium": ("Sodium", "mmol/L", {"mmol/l": 1, "meq/l": 1}),
    "glucose": ("Glucose", "mg/dL", {"mg/dl": 1, "mmol/l": 18.016}),
    "hemoglobin": ("Hemoglobin", "g/dL", {"g/dl": 1, "g/l": 0.1, "mmol/l": 1.611}),
    "platelets": ("Platelets", "10^9/L", {"10^9/l": 1, "x10^9/l": 1, "10^3/ul": 1, "k/ul": 1}),
    "wbc": ("White blood cells", "10^9/L", {"10^9/l": 1, "x10^9/l": 1, "10^3/ul": 1, "k/ul": 1}),
    "creatinine": ("Creatinine", "mg/dL", {"mg/dl": 1, "umol/l": 1 / 88.42, "µmol/l": 1 / 88.42}),
    "calcium": ("Calcium", "mg/dL", {"mg/dl": 1, "mmol/l": 4.008}),
    "inr": ("INR", "", {"": 1, "ratio": 1}),
    "alt": ("ALT", "U/L", {"u/l": 1, "iu/l": 1}),
    "tsh": ("TSH", "mIU/L", {"miu/l": 1, "uiu/ml": 1, "µiu/ml": 1}),
    "hba1c": ("HbA1c", "%", {"%": 1}),
    "cholesterol": ("Total cholesterol", "mg/dL", {"mg/dl": 1, "mmol/l": 38.67}),
}

ALIASES: dict[str, str] = {
    "potassium": "potassium",
    "k": "potassium",
    "k+": "potassium",
    "potassium, serum": "potassium",
    "sodium": "sodium",
    "na": "sodium",
    "na+": "sodium",
    "sodium, serum": "sodium",
    "glucose": "glucose",
    "glucose, fasting": "glucose",
    "fasting glucose": "glucose",
    "blood glucose": "glucose",
    "glu": "glucose",
    "hemoglobin": "hemoglobin",
    "haemoglobin": "hemoglobin",
    "hgb": "hemoglobin",
    "hb": "hemoglobin",
    "platelets": "platelets",
    "platelet count": "platelets",
    "plt": "platelets",
    "wbc": "wbc",
    "white blood cells": "wbc",
    "white blood cell count": "wbc",
    "leukocytes": "wbc",
    "creatinine": "creatinine",
    "creatinine, serum": "creatinine",
    "cr": "creatinine",
    "calcium": "calcium",
    "ca": "calcium",
    "calcium, total": "calcium",
    "inr": "inr",
    "pt/inr": "inr",
    "alt": "alt",
    "alanine aminotransferase": "alt",
    "sgpt": "alt",
    "tsh": "tsh",
    "thyroid stimulating hormone": "tsh",
    "hba1c": "hba1c",
    "hemoglobin a1c": "hba1c",
    "a1c": "hba1c",
    "cholesterol": "cholesterol",
    "total cholesterol": "cholesterol",
    "cholesterol, total": "cholesterol",
}

_NUMBER = r"[-+]?\d+(?:[.,]\d+)?"


@dataclass
class Measurement:
    test_name: str  # as printed
    canonical: str | None  # key in TESTS, or None if unknown
    display_name: str
    value: float | None
    unit: str
    ref_low: float | None
    ref_high: float | None

    def unit_is_canonical(self) -> bool:
        """True when the value is in the unit our critical rules expect."""
        return self.canonical is not None and self.unit == TESTS[self.canonical][1]


def canonical_test(name: str) -> str | None:
    key = re.sub(r"\s+", " ", name.strip().lower()).rstrip(":")
    return ALIASES.get(key)


def parse_number(text: str | None) -> float | None:
    """'6.8' -> 6.8, '<0.5' -> 0.5, '1,2' -> 1.2. None if no number."""
    if not text:
        return None
    match = re.search(_NUMBER, text.replace(" ", ""))
    return float(match.group().replace(",", ".")) if match else None


def parse_range(text: str | None) -> tuple[float | None, float | None]:
    """'3.5-5.1' -> (3.5, 5.1); '<200' -> (None, 200); '>40' -> (40, None)."""
    if not text:
        return None, None
    t = text.replace(" ", "").replace("–", "-").replace("—", "-")
    both = re.match(rf"^({_NUMBER})-({_NUMBER})", t)
    if both:
        return float(both.group(1).replace(",", ".")), float(both.group(2).replace(",", "."))
    upper = re.match(rf"^(?:<|<=|≤|upto)({_NUMBER})", t, re.I)
    if upper:
        return None, float(upper.group(1).replace(",", "."))
    lower = re.match(rf"^(?:>|>=|≥)({_NUMBER})", t)
    if lower:
        return float(lower.group(1).replace(",", ".")), None
    return None, None


def normalize(test_name: str, value_text: str, unit: str, ref_text: str) -> Measurement:
    """Convert to the canonical unit when the test and unit are known; otherwise keep as printed."""
    value = parse_number(value_text)
    low, high = parse_range(ref_text)
    key = canonical_test(test_name)
    unit_clean = unit.strip()
    if key:
        display, canonical_unit, factors = TESTS[key]
        factor = factors.get(unit_clean.lower().replace(" ", ""))
        if factor is not None:

            def convert(v: float | None, factor: float = factor) -> float | None:
                return round(v * factor, 1) if v is not None else None

            return Measurement(
                test_name, key, display, convert(value), canonical_unit, convert(low), convert(high)
            )
        return Measurement(test_name, key, display, value, unit_clean, low, high)
    return Measurement(test_name, None, test_name.strip(), value, unit_clean, low, high)
