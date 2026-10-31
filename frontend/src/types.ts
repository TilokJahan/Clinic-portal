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
  created_at: string
  reviewed_at: string | null
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
}
