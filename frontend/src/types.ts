// Types that mirror docs/api.md exactly (snake_case, ISO 8601 UTC strings).
// Display-only values (initials, formatted times, wait minutes) are derived in the UI.

export type Urgency = 'routine' | 'soon' | 'urgent'
export type AppointmentStatus = 'booked' | 'checked_in' | 'completed' | 'cancelled'

export interface Slot {
  id: number
  provider_id: number
  provider_name: string
  specialty: string
  starts_at: string
  ends_at: string
}

export interface Appointment {
  id: number
  patient_id: number
  slot_id: number
  status: AppointmentStatus
  created_at: string
}

export interface TriageRecord {
  id: number
  appointment_id: number
  ai_urgency: Urgency
  final_urgency: Urgency | null
  urgency: Urgency
  overridden: boolean
  suggested_specialty: string | null
  red_flags: string[]
  summary: string
  latency_ms: number | null
  tokens_used?: number | null
  created_at: string
  reviewed_at: string | null
}

export type LabFlag = 'normal' | 'low' | 'high' | 'critical_low' | 'critical_high' | 'unknown'
export type LabStatus = 'processing' | 'ready' | 'needs_review' | 'failed'

export interface LabResult {
  display_name: string
  test_name: string
  canonical: string | null
  value: number | null
  unit: string
  ref_low: number | null
  ref_high: number | null
  flag: LabFlag
  confidence: number | null
  needs_verification: boolean
  verification_reason: string | null
}

/** A lab report. Patients get results and the explanation only after a clinician approves. */
export interface LabReport {
  id: number
  appointment_id: number
  content_type: string
  status: LabStatus
  uploaded_at: string
  processed_at: string | null
  lab_urgency: Urgency | null
  reason: string | null
  clinician_summary: string | null
  patient_explanation: string | null
  explanation_approved: boolean
  explanation_approved_at: string | null
  extraction_confidence: number | null
  results: LabResult[]
}

export interface QueueLab {
  report_id: number
  status: LabStatus
  urgency: Urgency | null
  reason: string | null
  explanation_approved: boolean
}

export interface QueueEntry {
  appointment_id: number
  patient_label: string
  provider_id: number
  provider_name: string
  starts_at: string
  status: AppointmentStatus
  booked_at: string
  triage: TriageRecord | null
  lab: QueueLab | null
  /** The higher of symptom and lab urgency, unless a clinician decided after the lab came in */
  urgency: Urgency | null
}

// Every API call resolves to this instead of throwing, so pages can show the server's message.
// status 0 means the server could not be reached.
export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string }

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

export type Role = 'patient' | 'clinician' | 'admin'

export interface User {
  id: number
  email: string
  role: Role
}

/** A patient's own booking (GET /appointments). */
export interface MyAppointment {
  id: number
  slot_id: number
  status: AppointmentStatus
  created_at: string
  starts_at: string
  provider_name: string
  specialty: string
  intake_submitted: boolean
}

export interface Api {
  getSlots(date: string, providerId?: number): Promise<ApiResult<Slot[]>>
  /** Books for the signed-in patient (the backend takes the patient from the token). */
  book(slotId: number): Promise<ApiResult<Appointment>>
  myAppointments(): Promise<ApiResult<MyAppointment[]>>
  submitIntake(appointmentId: number, symptoms: string): Promise<ApiResult<TriageRecord>>
  getQueue(): Promise<ApiResult<QueueEntry[]>>
  /** Calls onQueue with the full queue on connect and after every change. Returns unsubscribe. */
  subscribeQueue(onQueue: (queue: QueueEntry[]) => void, onStatus: (s: StreamStatus) => void): () => void
  review(triageId: number, finalUrgency: Urgency): Promise<ApiResult<TriageRecord>>
  uploadLabReport(appointmentId: number, file: File): Promise<ApiResult<LabReport>>
  labReports(appointmentId: number): Promise<ApiResult<LabReport[]>>
  approveLabExplanation(reportId: number, text: string): Promise<ApiResult<LabReport>>
  /** The original file (clinicians), for checking extracted values against it */
  labReportFile(reportId: number): Promise<ApiResult<Blob>>
}
