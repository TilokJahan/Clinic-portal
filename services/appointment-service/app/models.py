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
    # Until auth is in place the patient is sent in the body. Later it comes from the JWT.
    patient_id: int = Field(gt=0)
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
