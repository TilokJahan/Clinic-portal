"""Lab reports: patients or lab technicians upload, the triage service interprets, clinicians
review and approve.

Flow: POST upload -> file stored (Blob/local) -> row "processing" -> background task sends the
file to the triage service's /labs/interpret -> results stored, status "ready"/"needs_review" ->
the queue updates live (NOTIFY trigger). A clinician approves (and may edit) the patient
explanation; until then the patient sees only that the report was received.
"""

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import psycopg
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import db, metrics
from app.auth import Clinician, CurrentUser, LabTech, Patient, require
from app.queue import patient_label
from app.storage import LabStore, get_store
from app.triage import TriageServiceClient, get_triage_client

logger = logging.getLogger("appointment.labs")

router = APIRouter()

Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]
Store = Annotated[LabStore, Depends(get_store)]
Triage = Annotated[TriageServiceClient, Depends(get_triage_client)]
# Who may read lab reports and results. Lab technicians upload; they don't read.
ReportReader = Annotated[CurrentUser, Depends(require("patient", "clinician", "admin"))]

MAX_BYTES = 10 * 1024 * 1024
EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
SCHEDULED = ("booked", "checked_in")


class LabResult(BaseModel):
    display_name: str
    test_name: str
    canonical: str | None
    value: float | None
    unit: str
    ref_low: float | None
    ref_high: float | None
    flag: str
    confidence: float | None
    needs_verification: bool
    verification_reason: str | None


class LabReport(BaseModel):
    id: int
    appointment_id: int
    content_type: str
    status: str
    uploaded_at: datetime
    processed_at: datetime | None
    # Hidden from patients until a clinician approves the explanation
    lab_urgency: str | None = None
    reason: str | None = None
    clinician_summary: str | None = None
    patient_explanation: str | None = None
    explanation_approved: bool
    explanation_approved_at: datetime | None
    extraction_confidence: float | None = None
    results: list[LabResult] = []


class WorklistReport(BaseModel):
    id: int
    status: str
    uploaded_at: datetime
    lab_urgency: str | None
    reason: str | None


class WorklistEntry(BaseModel):
    """A scheduled visit for the lab technician. No symptoms, triage or AI summaries."""

    appointment_id: int
    patient_label: str
    starts_at: datetime
    provider_name: str
    status: str
    reports: list[WorklistReport]


class ExplanationApproval(BaseModel):
    patient_explanation: str = Field(min_length=1, max_length=3000)


REPORT_COLUMNS = """
    r.id, r.appointment_id, r.content_type, r.status, r.uploaded_at, r.processed_at,
    r.lab_urgency, r.reason, r.clinician_summary, r.patient_explanation,
    r.explanation_approved_at IS NOT NULL AS explanation_approved, r.explanation_approved_at,
    r.extraction_confidence
"""


def _report(conn: psycopg.Connection, row: dict, for_patient: bool) -> LabReport:
    results = conn.execute(
        """
        SELECT display_name, test_name, canonical, value::float AS value, unit,
               ref_low::float AS ref_low, ref_high::float AS ref_high, flag, confidence,
               needs_verification, verification_reason
        FROM lab_results WHERE report_id = %s ORDER BY id
        """,
        (row["id"],),
    ).fetchall()
    report = LabReport(**row, results=[LabResult(**r) for r in results])
    if for_patient and not report.explanation_approved:
        # Nothing reaches a patient before a clinician has looked at it
        report = report.model_copy(
            update={
                "lab_urgency": None,
                "reason": None,
                "clinician_summary": None,
                "patient_explanation": None,
                "extraction_confidence": None,
                "results": [],
            }
        )
    elif for_patient:
        report = report.model_copy(update={"clinician_summary": None, "reason": None})
    return report


def process_report(
    report_id: int, content: bytes, content_type: str, triage: TriageServiceClient
) -> None:
    """Background task: interpret the report and store the results."""
    started = time.perf_counter()
    try:
        out = triage.interpret_lab(content, content_type)
    except Exception as exc:  # the triage service is down or rejected the file
        logger.warning(
            "lab interpretation failed for report %s (%s)", report_id, type(exc).__name__
        )
        with db.connection() as conn:
            conn.execute(
                "UPDATE lab_reports SET status = 'failed', processed_at = now() WHERE id = %s",
                (report_id,),
            )
            conn.commit()
        metrics.LAB_PROCESSED.labels("failed").inc()
        return
    latency_ms = round((time.perf_counter() - started) * 1000)
    with db.connection() as conn, conn.transaction():
        conn.execute(
            """
            UPDATE lab_reports SET status = %s, lab_urgency = %s, reason = %s,
                clinician_summary = %s, patient_explanation = %s, extraction_confidence = %s,
                tokens_used = %s, latency_ms = %s, processed_at = now()
            WHERE id = %s
            """,
            (
                out["status"],
                out["urgency"],
                out["reason"],
                out["clinician_summary"],
                out["patient_explanation"],
                out["extraction_confidence"],
                out["tokens_used"],
                latency_ms,
                report_id,
            ),
        )
        for r in out["results"]:
            conn.execute(
                """
                INSERT INTO lab_results (report_id, test_name, display_name, canonical, value, unit,
                    ref_low, ref_high, flag, confidence, needs_verification, verification_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report_id,
                    r["test_name"],
                    r["display_name"],
                    r["canonical"],
                    r["value"],
                    r["unit"],
                    r["ref_low"],
                    r["ref_high"],
                    r["flag"],
                    r["confidence"],
                    r["needs_verification"],
                    r["verification_reason"],
                ),
            )
    metrics.LAB_PROCESSED.labels(out["status"]).inc()
    metrics.LAB_PROCESSING_SECONDS.observe(latency_ms / 1000)


def _accept_upload(
    conn: psycopg.Connection,
    user: CurrentUser,
    store: LabStore,
    triage: TriageServiceClient,
    background: BackgroundTasks,
    appointment_id: int,
    file: UploadFile,
    *,
    own_only: bool,
) -> LabReport:
    """Store an uploaded report and queue it for reading; shared by patients and lab techs.

    own_only: patients may only upload to their own appointment (anything else is a 404, so
    nobody learns which ids exist) and can't upload to a cancelled one. Lab technicians may
    upload for any patient, but only while the visit is still scheduled (booked or checked in).
    """
    appointment = conn.execute(
        "SELECT status, patient_id FROM appointments WHERE id = %s", (appointment_id,)
    ).fetchone()
    if appointment is None or (own_only and appointment["patient_id"] != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if appointment["status"] == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is cancelled")
    if not own_only and appointment["status"] not in SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is already completed")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a PDF, PNG or JPEG")
    content = file.file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is empty")
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The file is over 10 MB")

    blob_name = f"{appointment_id}/{uuid.uuid4()}{EXTENSIONS[content_type]}"
    store.save(blob_name, content, content_type)
    row = conn.execute(
        f"""
        INSERT INTO lab_reports AS r
            (appointment_id, blob_name, content_type, size_bytes, uploaded_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING {REPORT_COLUMNS}
        """,
        (appointment_id, blob_name, content_type, len(content), user.id),
    ).fetchone()
    conn.commit()  # visible to the background task
    metrics.LAB_UPLOADS.labels(content_type, user.role).inc()
    background.add_task(process_report, row["id"], content, content_type, triage)
    # The uploader gets the patient's view: just that the report was received
    return _report(conn, row, for_patient=True)


@router.post("/appointments/{appointment_id}/lab-reports", status_code=status.HTTP_202_ACCEPTED)
def upload_lab_report(
    conn: Conn,
    user: Patient,
    store: Store,
    triage: Triage,
    background: BackgroundTasks,
    appointment_id: int,
    file: Annotated[UploadFile, File(description="PDF, PNG or JPEG, up to 10 MB")],
) -> LabReport:
    """Attach a lab report to your appointment. It's read in the background (202)."""
    return _accept_upload(
        conn, user, store, triage, background, appointment_id, file, own_only=True
    )


@router.post("/lab/appointments/{appointment_id}/reports", status_code=status.HTTP_202_ACCEPTED)
def upload_lab_report_as_tech(
    conn: Conn,
    user: LabTech,
    store: Store,
    triage: Triage,
    background: BackgroundTasks,
    appointment_id: int,
    file: Annotated[UploadFile, File(description="PDF, PNG or JPEG, up to 10 MB")],
) -> LabReport:
    """Lab technicians: attach a report to any scheduled (booked or checked-in) appointment."""
    return _accept_upload(
        conn, user, store, triage, background, appointment_id, file, own_only=False
    )


@router.get("/lab/worklist")
def lab_worklist(
    conn: Conn,
    _: LabTech,
    day: Annotated[date | None, Query(alias="date", description="YYYY-MM-DD (UTC)")] = None,
) -> list[WorklistEntry]:
    """Scheduled visits that start on the day (default: today), earliest first.

    Only what a technician needs: who (a label, never a name), when, with whom, and the status
    of any reports. Symptoms, triage results and AI summaries are not included.
    """
    start = datetime.combine(day or datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    rows = conn.execute(
        """
        SELECT a.id AS appointment_id, a.patient_id, a.status, s.starts_at,
               p.name AS provider_name
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN providers p ON p.id = s.provider_id
        WHERE a.status = ANY(%(statuses)s)
          AND s.starts_at >= %(start)s AND s.starts_at < %(end)s
        ORDER BY s.starts_at, a.id
        """,
        {"statuses": list(SCHEDULED), "start": start, "end": start + timedelta(days=1)},
    ).fetchall()
    reports = conn.execute(
        """
        SELECT appointment_id, id, status, uploaded_at, lab_urgency, reason
        FROM lab_reports WHERE appointment_id = ANY(%s) ORDER BY uploaded_at DESC, id DESC
        """,
        ([row["appointment_id"] for row in rows],),
    ).fetchall()
    by_appointment: dict[int, list[WorklistReport]] = {}
    for r in reports:
        by_appointment.setdefault(r["appointment_id"], []).append(
            WorklistReport(**{k: v for k, v in r.items() if k != "appointment_id"})
        )
    return [
        WorklistEntry(
            appointment_id=row["appointment_id"],
            patient_label=patient_label(row["patient_id"]),
            starts_at=row["starts_at"],
            provider_name=row["provider_name"],
            status=row["status"],
            reports=by_appointment.get(row["appointment_id"], []),
        )
        for row in rows
    ]


@router.get("/appointments/{appointment_id}/lab-reports")
def list_lab_reports(conn: Conn, user: ReportReader, appointment_id: int) -> list[LabReport]:
    """Patients: their own (results only after approval). Clinicians: everything.

    Lab technicians get 403: they upload reports, they don't read them.
    """
    is_patient = user.role == "patient"
    owner = conn.execute(
        "SELECT patient_id FROM appointments WHERE id = %s", (appointment_id,)
    ).fetchone()
    if owner is None or (is_patient and owner["patient_id"] != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    rows = conn.execute(
        f"SELECT {REPORT_COLUMNS} FROM lab_reports r WHERE r.appointment_id = %s "
        "ORDER BY r.uploaded_at DESC",
        (appointment_id,),
    ).fetchall()
    return [_report(conn, row, for_patient=is_patient) for row in rows]


@router.patch("/lab-reports/{report_id}")
def approve_explanation(
    conn: Conn, user: Clinician, report_id: int, body: ExplanationApproval
) -> LabReport:
    """Approve (and possibly edit) the explanation the patient will see."""
    row = conn.execute(
        f"""
        UPDATE lab_reports AS r SET patient_explanation = %s, explanation_approved_at = now(),
            explanation_approved_by = %s
        WHERE r.id = %s AND r.status IN ('ready', 'needs_review')
        RETURNING {REPORT_COLUMNS}
        """,
        (body.patient_explanation.strip(), user.id, report_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lab report not found or not read yet")
    metrics.LAB_APPROVALS.inc()
    return _report(conn, row, for_patient=False)


@router.get("/lab-reports/{report_id}/file")
def lab_report_file(conn: Conn, _: Clinician, store: Store, report_id: int) -> Response:
    """The original report, for the clinician to check against the extracted values."""
    row = conn.execute(
        "SELECT blob_name, content_type FROM lab_reports WHERE id = %s", (report_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lab report not found")
    return Response(
        store.read(row["blob_name"]),
        media_type=row["content_type"],
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )
