"""Which tests a patient's symptoms suggest, and whether a recent result is on file.

Fixed keyword rules, not the AI: they are predictable, easy to review, and only ever *suggest*.
The suggestion lets the booking page ask "do you have a recent result?" and tells the clinician
when one is missing or out of date, so they can request it from the lab. The symptom text is
only read here, never stored.
"""

import re

# Every kind of test the portal handles, with the label people see
EXAM_TYPES = {
    "blood": "Blood test",
    "urine": "Urine test",
    "ultrasound": "Ultrasound",
    "xray": "X-ray",
    "ct": "CT scan",
    "mri": "MRI",
    "ecg": "ECG (heart tracing)",
    "other": "Other test",
}
# Reports with a table of values the OCR pipeline can read; the others (imaging, ECG) are read
# by a clinician
TABLE_EXAMS = ("blood", "urine")
# A result older than this no longer counts for a new visit
RECENT_DAYS = 40

_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "blood",
        (
            "tired",
            "fatigue",
            "exhausted",
            "weak",
            "dizzy",
            "pale",
            "fever",
            "infection",
            "weight loss",
            "losing weight",
            "thirst",
            "thirsty",
            "diabet",
            "anemi",
            "anaemi",
            "bruis",
            "jaundice",
            "yellow skin",
            "night sweats",
            "swollen gland",
            "palpitation",
        ),
    ),
    (
        "urine",
        (
            "burning when",
            "burns when",
            "pain when i pee",
            "painful urination",
            "urinat",
            "pee ",
            "peeing",
            "blood in my urine",
            "blood in urine",
            "cloudy urine",
            "uti",
            "bladder",
        ),
    ),
    (
        "ultrasound",
        (
            "abdominal pain",
            "abdomen",
            "stomach pain",
            "belly pain",
            "lower right",
            "pelvic pain",
            "pregnan",
            "lump in my breast",
            "breast lump",
            "gallbladder",
            "kidney stone",
            "flank pain",
            "swollen leg",
            "swelling in my leg",
            "testic",
        ),
    ),
    (
        "xray",
        (
            "fracture",
            "broken",
            "broke my",
            "fell on",
            "fell down",
            "had a fall",
            "twisted",
            "sprain",
            "cough for weeks",
            "coughing for weeks",
            "persistent cough",
            "chest infection",
            "pneumonia",
        ),
    ),
    (
        "mri",
        (
            "numb",
            "tingling",
            "back pain down my leg",
            "sciatica",
            "knee injury",
            "ligament",
            "seizure",
            "headaches for weeks",
            "migraine",
            "memory",
            "vision loss",
            "blurred vision",
        ),
    ),
    (
        "ct",
        ("head injury", "hit my head", "worst headache", "severe headache", "car accident"),
    ),
    (
        "ecg",
        (
            "chest pain",
            "chest pressure",
            "palpitation",
            "heart racing",
            "racing heart",
            "irregular heartbeat",
            "skipped beat",
            "faint",
            "passed out",
            "short of breath",
        ),
    ),
]


def suggested_tests(symptoms: str) -> list[str]:
    """The tests these symptoms suggest, in a fixed order, without repeats."""
    text = " " + re.sub(r"\s+", " ", symptoms.lower()) + " "
    return [exam for exam, words in _RULES if any(w in text for w in words)]


# For queries on appointments a with triage_results t: each suggested test and what is on file
# for it. "requested" (the lab was asked), "recent" (a result from the last RECENT_DAYS days),
# "outdated" (only older results) or "missing".
LAB_NEEDS_SQL = f"""(
    SELECT coalesce(jsonb_agg(jsonb_build_object('exam_type', st.exam, 'status',
        CASE
            WHEN EXISTS (
                SELECT 1 FROM lab_requests q WHERE q.appointment_id = a.id
                  AND q.exam_type = st.exam AND q.status IN ('requested', 'scheduled')
            ) THEN 'requested'
            WHEN EXISTS (
                SELECT 1 FROM lab_reports r WHERE r.appointment_id = a.id
                  AND r.exam_type = st.exam
                  AND coalesce(r.taken_on, r.uploaded_at::date)
                      >= current_date - {RECENT_DAYS}
            ) THEN 'recent'
            WHEN EXISTS (
                SELECT 1 FROM lab_reports r WHERE r.appointment_id = a.id AND r.exam_type = st.exam
            ) THEN 'outdated'
            ELSE 'missing'
        END) ORDER BY st.ord), '[]'::jsonb)
    FROM unnest(coalesce(t.suggested_tests, '{{}}'::text[])) WITH ORDINALITY AS st (exam, ord)
)"""

# The lab requests for appointment a, newest first (the note is for staff only)
LAB_REQUESTS_SQL = """(
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'id', q.id, 'exam_type', q.exam_type, 'urgency', q.urgency, 'status', q.status,
        'note', q.note, 'requested_at', q.requested_at) ORDER BY q.requested_at DESC), '[]'::jsonb)
    FROM lab_requests q WHERE q.appointment_id = a.id AND q.status <> 'cancelled'
)"""
