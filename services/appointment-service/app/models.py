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
