from datetime import datetime
from enum import StrEnum

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


class AppointmentCreate(BaseModel):
    # The patient comes from the sign-in token, never from the body.
    slot_id: int = Field(gt=0)


class Appointment(BaseModel):
    id: int
    patient_id: int
    slot_id: int
    status: AppointmentStatus
    created_at: datetime


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
    appointment_id: int
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
    # Urgent, booked more than 24 hours from now, and no open offer: offer an earlier visit
    needs_earlier_visit: bool = False
    # An earlier visit has been offered and the patient hasn't answered yet
    offer_pending: bool = False


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
    # An earlier slot the patient can accept or decline; None if there is no open offer
    pending_offer: PendingOffer | None = None


class RescheduleOfferCreate(BaseModel):
    slot_id: int = Field(gt=0)
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


class OfferResult(BaseModel):
    id: int
    status: str


class Timeframe(BaseModel):
    hours: int
    label: str


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


class RescheduleRequest(BaseModel):
    slot_id: int = Field(gt=0)
