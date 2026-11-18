from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Slot(BaseModel):
    id: int
    provider_id: int
    provider_name: str
    specialty: str
    starts_at: datetime
    ends_at: datetime
    # Held for urgent patients (the urgent reserve); only listed to urgent patients and clinicians
    reserved: bool = False
    # False for a time that is already booked (or kept for urgent care), when a day is listed
    # with include_booked: shown, but can't be chosen
    available: bool = True


class AppointmentCreate(BaseModel):
    # The patient comes from the sign-in token, never from the body.
    slot_id: int = Field(gt=0)
    # The patient's own assessment from POST /assessments (symptoms first). Its urgency limits
    # which times may be requested, and it is linked to the new appointment.
    assessment_id: int | None = Field(default=None, gt=0)
    # Or the symptoms themselves, assessed with the request; never stored. With neither, the
    # request waits until POST /intake.
    symptoms: str | None = Field(default=None, min_length=1, max_length=4000)


class AssessmentCreate(BaseModel):
    # Sent on to the triage service (which redacts it) and never stored here.
    symptoms: str = Field(min_length=1, max_length=4000)


class Appointment(BaseModel):
    id: int
    patient_id: int
    slot_id: int
    status: AppointmentStatus
    created_at: datetime
    # None while the request waits for a clinician's approval
    approved_at: datetime | None = None


class Urgency(StrEnum):
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"


class IntakeCreate(BaseModel):
    appointment_id: int = Field(gt=0)
    # Sent on to the triage service (which redacts it) and never stored here.
    symptoms: str = Field(min_length=1, max_length=4000)


class TriageAssessment(BaseModel):
    """What the triage service returns (see "Triage result" in docs/api.md)."""

    urgency: Urgency
    suggested_specialty: str
    red_flags: list[str] = []
    summary: str
    tokens_used: int | None = None  # reported by the Azure OpenAI client; None for the fake
    # True when this is a safe default rather than a real AI answer
    fallback: bool = False


class TriageRecord(BaseModel):
    id: int
    # None for an assessment that isn't linked to a booking yet
    appointment_id: int | None
    ai_urgency: Urgency
    final_urgency: Urgency | None
    # final_urgency once a clinician has reviewed, otherwise ai_urgency
    urgency: Urgency
    overridden: bool
    suggested_specialty: str | None
    red_flags: list[str]
    summary: str
    latency_ms: int | None
    tokens_used: int | None = None
    created_at: datetime
    reviewed_at: datetime | None
    # Tests the symptoms suggest (fixed rules, app/lab_needs.py), e.g. ["blood", "ultrasound"]
    suggested_tests: list[str] = []


class Assessment(BaseModel):
    """The result of describing symptoms before booking, and what it allows."""

    triage: TriageRecord
    # The latest a visit should be: the patient may only request times within this many hours,
    # unless nothing at all is free that soon
    max_within_hours: int


ExamType = Literal["blood", "urine", "ultrasound", "xray", "ct", "mri", "ecg", "other"]


class LabNeed(BaseModel):
    """A suggested test and what is on file: recent (last 40 days), outdated, missing, or
    requested from the lab."""

    exam_type: ExamType
    status: Literal["recent", "outdated", "missing", "requested"]


class LabRequestCreate(BaseModel):
    exam_type: ExamType
    urgency: Urgency
    # For the lab: what to test and why. Not shown to the patient.
    note: str | None = Field(default=None, max_length=500)


class LabRequestSummary(BaseModel):
    id: int
    exam_type: ExamType
    urgency: Urgency
    status: Literal["requested", "proposed", "scheduled", "completed", "cancelled"]
    requested_at: datetime
    # Staff only; None in the patient's view
    note: str | None = None
    # Lab times offered to the patient, and the one they booked
    proposed_times: list[datetime] = []
    scheduled_at: datetime | None = None


class TriageReview(BaseModel):
    final_urgency: Urgency


class QueueEntry(BaseModel):
    appointment_id: int
    # A label instead of a name or email: the queue screen only needs to tell patients apart.
    patient_label: str
    provider_id: int
    provider_name: str
    starts_at: datetime
    status: AppointmentStatus
    booked_at: datetime
    # None until the patient submits an intake
    triage: TriageRecord | None
    # Latest lab report, if any
    lab: "QueueLab | None" = None
    # What the queue sorts by: the higher of symptom and lab urgency, unless a clinician has
    # decided after the latest lab result came in (then their decision)
    urgency: Urgency | None = None
    # Later than the priority allows (urgent: 24 hours, soon: 3 days) and no open offer: offer an
    # earlier visit or call the patient
    needs_earlier_visit: bool = False
    # An earlier visit has been offered and the patient hasn't answered yet
    offer_pending: bool = False
    # A booking request no clinician has approved yet
    awaiting_approval: bool = False
    # The patient said none of the proposed times work, and why (until new times are proposed)
    offer_declined_note: str | None = None
    # Suggested tests and whether a recent result is on file; open and done lab requests
    lab_needs: list[LabNeed] = []
    lab_requests: list[LabRequestSummary] = []
    # The physician's summary once the visit is completed
    visit_summary: str | None = None


class QueueLab(BaseModel):
    report_id: int
    status: str
    urgency: Urgency | None
    reason: str | None
    explanation_approved: bool


class DevLogin(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # Checked against DEMO_PASSCODE when the operator has set one (see app/main.py)
    passcode: str = Field(default="", max_length=200)


class UserOut(BaseModel):
    id: int
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PendingOffer(BaseModel):
    """An earlier visit the care team has offered, as the patient sees it. No clinical detail."""

    id: int
    slot_id: int
    starts_at: datetime
    provider_name: str


class MyAppointment(BaseModel):
    """A patient's own booking, as listed by GET /appointments."""

    id: int
    slot_id: int
    status: AppointmentStatus
    created_at: datetime
    starts_at: datetime
    provider_name: str
    specialty: str
    intake_submitted: bool
    # False while a clinician hasn't approved the request yet
    approved: bool = True
    # The care team declined the request (status is then "cancelled"); the reason, if they gave one
    declined: bool = False
    decline_reason: str | None = None
    # What the visit is about: the triage priority and summary of the patient's symptoms
    priority: Urgency | None = None
    reason_summary: str | None = None
    # Suggested tests and what is on file; tests the care team asked the lab for
    lab_needs: list[LabNeed] = []
    lab_requests: list[LabRequestSummary] = []
    lab_report_count: int = 0
    # Written by the physician when the visit is completed
    visit_summary: str | None = None
    completed_at: datetime | None = None
    # Times the care team proposed (at most three); the patient accepts one or declines them all
    pending_offers: list[PendingOffer] = []
    # The first of them, for older clients
    pending_offer: PendingOffer | None = None


class RescheduleOfferCreate(BaseModel):
    # One time, or up to three for the patient to choose from
    slot_id: int | None = Field(default=None, gt=0)
    slot_ids: list[int] | None = Field(default=None, min_length=1, max_length=3)
    # For the care team only; never shown to the patient
    reason: str | None = Field(default=None, max_length=500)


class RescheduleOffer(BaseModel):
    """An offer as the clinician sees it."""

    id: int
    appointment_id: int
    proposed_slot_id: int
    provider_name: str
    starts_at: datetime
    status: str
    reason: str | None
    created_at: datetime


class DeclineRequest(BaseModel):
    # Shown to the patient
    reason: str | None = Field(default=None, max_length=500)


class OfferResult(BaseModel):
    id: int
    status: str


class Timeframe(BaseModel):
    hours: int
    label: str


class TimeframeAvailability(Timeframe):
    # Free times inside the timeframe (0: the button is shown disabled)
    free: int
    # False when the patient's urgency doesn't allow a timeframe this long
    allowed: bool = True


class OffersDecline(BaseModel):
    # Why none of the proposed times work. Shown to the clinician.
    note: str | None = Field(default=None, max_length=500)


class UrgencyLevel(BaseModel):
    """One row of the urgency matrix (see app/urgency.py)."""

    urgency: Urgency
    seen_within_hours: int
    seen_within: str
    symptom_signals: list[str]
    lab_signals: list[str]
    action: str


class UrgencyMatrix(BaseModel):
    levels: list[UrgencyLevel]
    rules: list[str]
    timeframes: list[Timeframe]


class ScheduleOptions(BaseModel):
    """Times a patient can move their visit to, within the timeframe they chose."""

    appointment_id: int
    starts_at: datetime
    # The symptom priority the patient was shown after their intake (None before an intake)
    priority: Urgency | None
    # The latest they may choose. Can be stricter than their own priority when the care team
    # (a lab result or a clinician's review) needs them sooner; care_team_limit says so.
    max_within_hours: int
    care_team_limit: bool
    within_hours: int
    # True when the current visit already falls inside the chosen timeframe
    current_fits: bool
    slots: list[Slot]
    # When nothing is free in the timeframe: the first free time after it, or None if there is
    # none at all. The patient may take it if it is earlier than their current visit.
    next_available: Slot | None = None


class RescheduleRequest(BaseModel):
    slot_id: int = Field(gt=0)


class VisitCompletion(BaseModel):
    # What the patient reads afterwards: findings, advice, next steps
    summary: str = Field(min_length=1, max_length=3000)


class Provider(BaseModel):
    id: int
    name: str
    specialty: str


class AdminUser(BaseModel):
    id: int
    email: str
    role: Literal["patient", "clinician", "physician", "admin", "lab_tech"]
    provider_id: int | None
    provider_name: str | None
    # False: the account can't sign in
    active: bool = True


class AdminUserUpdate(BaseModel):
    role: Literal["patient", "clinician", "physician", "admin", "lab_tech"]
    # Required for a physician: whose schedule they see
    provider_id: int | None = Field(default=None, gt=0)
    # Disable (false) or enable (true) the account; unchanged when left out
    active: bool | None = None


class LabRequestEntry(BaseModel):
    """A lab request as the lab technician sees it: what, how urgent, for whom and when. No
    symptoms or AI summaries."""

    id: int
    appointment_id: int
    patient_label: str
    exam_type: ExamType
    urgency: Urgency
    note: str | None
    status: Literal["requested", "proposed", "scheduled", "completed", "cancelled"]
    requested_at: datetime
    requested_by_role: str
    proposed_times: list[datetime] = []
    scheduled_at: datetime | None = None
    visit_starts_at: datetime
    provider_name: str


class LabRequestUpdate(BaseModel):
    status: Literal["scheduled", "cancelled"]
