"""The urgency matrix: how a priority is decided, and how soon each priority should be seen.

One place for the rules that the queue, the patient's scheduling choices and the "How priority is
decided" screen all follow (GET /urgency-matrix sends this to the frontend). The SQL that applies
the combining rule is EFFECTIVE_URGENCY in app/queue.py. docs/triage.md explains it in prose.
"""

from app.models import Timeframe, Urgency, UrgencyLevel, UrgencyMatrix

# The latest a patient at each level should be seen, counted from now. Patients choose any
# timeframe up to this one, never a later one.
SEEN_WITHIN_HOURS = {Urgency.URGENT: 24, Urgency.SOON: 72, Urgency.ROUTINE: 14 * 24}
# Before an intake there is no priority yet, so any timeframe is allowed
NO_PRIORITY_HOURS = 14 * 24

# The urgent reserve: each provider keeps one 30-minute slot a day free for urgent patients, each
# at a different time so urgent patients have a choice (is_urgent_reserve() in
# schemav6_urgent_reserve.sql). It is never opened to ordinary booking: it is how the clinic can
# always give an urgent patient a visit. Only urgent patients and clinician offers can use it.
# SQL for a slot "s" that anyone may book
OPEN_TO_ALL = "(NOT s.reserved_for_urgent)"

RESERVED_MESSAGE = "That time is kept free for urgent care. Please pick another."

TIMEFRAMES = [
    Timeframe(hours=24, label="Within 24 hours"),
    Timeframe(hours=72, label="Within 3 days"),
    Timeframe(hours=7 * 24, label="Within 1 week"),
    Timeframe(hours=14 * 24, label="Within 2 weeks"),
]
TIMEFRAME_HOURS = {t.hours for t in TIMEFRAMES}

LEVELS = [
    UrgencyLevel(
        urgency=Urgency.URGENT,
        seen_within_hours=SEEN_WITHIN_HOURS[Urgency.URGENT],
        seen_within="Within 24 hours",
        symptom_signals=[
            "A red-flag rule matches: chest pain or pressure, trouble breathing, stroke signs, "
            "fainting, severe bleeding, allergic swelling, worst-ever headache, or self-harm risk",
            "The AI judges the symptoms urgent",
            "The AI's safety filter refused the message (treated as urgent until a clinician "
            "reads it)",
        ],
        lab_signals=["Any critical value (critical low or critical high)"],
        action="Top of the queue. The patient sees an emergency notice and can only choose a "
        "visit within 24 hours, including the slots kept free for urgent care; a clinician can "
        "offer an earlier slot.",
    ),
    UrgencyLevel(
        urgency=Urgency.SOON,
        seen_within_hours=SEEN_WITHIN_HOURS[Urgency.SOON],
        seen_within="Within 3 days",
        symptom_signals=[
            "The AI judges the symptoms new, worsening or needing a check this week",
            "The AI could not be reached (safe default until a clinician reviews)",
        ],
        lab_signals=[
            "Any value outside the reference range (low or high)",
            "A report that could not be read",
        ],
        action="Ahead of routine patients. The patient chooses a visit within 3 days.",
    ),
    UrgencyLevel(
        urgency=Urgency.ROUTINE,
        seen_within_hours=SEEN_WITHIN_HOURS[Urgency.ROUTINE],
        seen_within="Within 2 weeks",
        symptom_signals=["The AI judges the symptoms mild, stable or long-standing"],
        lab_signals=["All values within the reference range"],
        action="Seen in order of arrival. The patient chooses any visit within 2 weeks.",
    ),
]

RULES = [
    "The priority is the higher of the symptom priority and the lab priority (see the grid).",
    "Fixed rules decide red flags and critical lab values. The AI can raise a priority but never "
    "lower one set by a rule.",
    "A clinician reviews every AI suggestion. A clinician's decision made after the latest lab "
    "result is final.",
    "Patients choose when to come within the time allowed for their priority, never later. "
    "Nothing is moved until the patient accepts. If nothing is free in time, they can still take "
    "any time earlier than their current visit, and the clinician queue flags them.",
    "Each doctor keeps one 30-minute slot a day free for urgent patients, each at a different "
    "time so there is a choice across the day. Only urgent patients and clinicians can use it, so "
    "the clinic can always give an urgent patient a visit.",
]


def max_within_hours(urgency: Urgency | None) -> int:
    return SEEN_WITHIN_HOURS[urgency] if urgency else NO_PRIORITY_HOURS


def matrix() -> UrgencyMatrix:
    return UrgencyMatrix(levels=LEVELS, rules=RULES, timeframes=TIMEFRAMES)
