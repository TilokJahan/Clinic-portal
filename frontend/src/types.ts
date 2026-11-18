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
  /** Kept free for urgent patients (shown only to them and to clinicians) */
  reserved?: boolean
  /** false for a booked time when a whole day is listed: shown greyed out, can't be chosen */
  available?: boolean
}

/** Step 1 of booking: the symptoms' triage, and how soon the patient should be seen */
export interface Assessment {
  triage: TriageRecord
  max_within_hours: number
}

export interface TimeframeAvailability {
  hours: number
  label: string
  /** Free times inside the timeframe; 0 means the button is greyed out */
  free: number
  /** false when the patient's priority doesn't allow a timeframe this long */
  allowed: boolean
}

export interface Appointment {
  id: number
  patient_id: number
  slot_id: number
  status: AppointmentStatus
  created_at: string
  /** null while the request waits for a clinician's approval */
  approved_at?: string | null
}

export interface TriageRecord {
  id: number
  /** null for an assessment made before booking, until a time is requested with it */
  appointment_id: number | null
  ai_urgency: Urgency
  final_urgency: Urgency | null
  urgency: Urgency
  overridden: boolean
  suggested_specialty: string | null
  /** Tests the symptoms suggest (fixed rules), e.g. ["blood", "ultrasound"] */
  suggested_tests?: ExamType[]
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
  exam_type?: ExamType
  /** When the test was done (YYYY-MM-DD), if known */
  taken_on?: string | null
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

/** Limited report metadata returned to lab technicians; no extracted results or AI summaries. */
export interface WorklistReport {
  id: number
  exam_type?: ExamType
  status: LabStatus
  uploaded_at: string
  lab_urgency: Urgency | null
  reason: string | null
}

export interface LabWorklistEntry {
  appointment_id: number
  patient_label: string
  starts_at: string
  provider_name: string
  status: 'booked' | 'checked_in'
  reports: WorklistReport[]
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
  /** Later than the priority allows (urgent: 24 h, soon: 3 days) and no open offer */
  needs_earlier_visit?: boolean
  /** An earlier visit was offered and the patient hasn't answered yet */
  offer_pending?: boolean
  /** A booking request no clinician has approved yet */
  awaiting_approval?: boolean
  /** The patient said none of the proposed times work ('' when they gave no reason) */
  offer_declined_note?: string | null
  /** Suggested tests and what is on file; tests requested from the lab */
  lab_needs?: LabNeed[]
  lab_requests?: LabRequestSummary[]
  /** The physician's summary once the visit is completed */
  visit_summary?: string | null
}

// Every API call resolves to this instead of throwing, so pages can show the server's message.
// status 0 means the server could not be reached.
export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string }

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

export type Role = 'patient' | 'clinician' | 'physician' | 'admin' | 'lab_tech'

export type ExamType = 'blood' | 'urine' | 'ultrasound' | 'xray' | 'ct' | 'mri' | 'ecg' | 'other'

/** A suggested test and what is on file for it (last 40 days counts as recent) */
export interface LabNeed {
  exam_type: ExamType
  status: 'recent' | 'outdated' | 'missing' | 'requested'
}

export interface LabRequestSummary {
  id: number
  exam_type: ExamType
  urgency: Urgency
  status: 'requested' | 'proposed' | 'scheduled' | 'completed' | 'cancelled'
  requested_at: string
  /** For the lab; null in the patient's view */
  note: string | null
  /** Lab times offered to the patient, and the one they booked */
  proposed_times?: string[]
  scheduled_at?: string | null
}

/** Free lab times for a request, within how soon its urgency needs the test */
export interface LabTimes {
  within_hours: number
  /** false when nothing is free in time: these are the first free times after */
  in_time: boolean
  times: string[]
}

/** A lab request as the lab technician sees it (no symptoms or AI summaries) */
export interface LabRequestEntry extends LabRequestSummary {
  appointment_id: number
  patient_label: string
  requested_by_role: string
  visit_starts_at: string
  provider_name: string
}

export interface Provider {
  id: number
  name: string
  specialty: string
}

export interface AdminUser {
  id: number
  email: string
  role: Role
  provider_id: number | null
  provider_name: string | null
  /** false: the account can't sign in */
  active?: boolean
}

export type InvitationStatus = 'pending' | 'accepted' | 'expired' | 'revoked'

export interface Invitation {
  id: number
  email: string
  role: Role
  provider_id: number | null
  provider_name: string | null
  created_at: string
  expires_at: string
  status: InvitationStatus
  /** Path of the invite link (add the site's origin); only while pending */
  link: string | null
}

/** What someone who opens an invite link sees */
export interface InvitationView {
  email: string
  role: Role
  provider_name: string | null
  status: InvitationStatus
  expires_at: string
  /** "accept" in the demo; "sign_up" with Entra External ID */
  method: 'accept' | 'sign_up'
}

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
  /** false while a clinician hasn't approved the request yet */
  approved?: boolean
  /** The care team declined the request (status is then 'cancelled'), with their reason if given */
  declined?: boolean
  decline_reason?: string | null
  /** What the visit is about: the priority and the summary of the patient's symptoms */
  priority?: Urgency | null
  reason_summary?: string | null
  lab_needs?: LabNeed[]
  lab_requests?: LabRequestSummary[]
  lab_report_count?: number
  /** Written by the physician when the visit is completed */
  visit_summary?: string | null
  completed_at?: string | null
  /** Times the care team proposed (up to three); the patient accepts one or declines them all */
  pending_offers?: PendingOffer[]
  /** The first of them */
  pending_offer?: PendingOffer | null
}

export interface PendingOffer {
  id: number
  slot_id: number
  starts_at: string
  provider_name: string
}

/** An earlier-visit offer as the clinician sees it. */
export interface RescheduleOffer {
  id: number
  appointment_id: number
  proposed_slot_id: number
  provider_name: string
  starts_at: string
  status: 'pending' | 'accepted' | 'declined' | 'expired'
  reason: string | null
  created_at: string
}

export interface Timeframe {
  hours: number
  label: string
}

/** One row of the urgency matrix (GET /urgency-matrix). */
export interface UrgencyLevel {
  urgency: Urgency
  seen_within_hours: number
  seen_within: string
  symptom_signals: string[]
  lab_signals: string[]
  action: string
}

export interface UrgencyMatrix {
  levels: UrgencyLevel[]
  rules: string[]
  timeframes: Timeframe[]
}

/** Times a patient can move a visit to, within the timeframe they chose. */
export interface ScheduleOptions {
  appointment_id: number
  starts_at: string
  /** The priority the patient was shown after their intake */
  priority: Urgency | null
  /** The latest they may choose; care_team_limit is true when that is stricter than priority */
  max_within_hours: number
  care_team_limit: boolean
  within_hours: number
  /** The current visit is already inside the chosen timeframe */
  current_fits: boolean
  slots: Slot[]
  /** When nothing is free in the timeframe: the first free time after it (null if none) */
  next_available?: Slot | null
}

export interface Api {
  /** Free times on a day; with includeBooked, every time of the day (booked ones available=false) */
  getSlots(date: string, providerId?: number, options?: { includeBooked?: boolean; urgent?: boolean }): Promise<ApiResult<Slot[]>>
  /** Step 1 of booking: describe symptoms, get the priority and how soon to be seen */
  assess(symptoms: string): Promise<ApiResult<Assessment>>
  /** Each timeframe with its free times, and whether the priority allows it */
  timeframeAvailability(priority?: Urgency | null): Promise<ApiResult<TimeframeAvailability[]>>
  /** Requests a time for the signed-in patient (the backend takes the patient from the token).
   *  The symptoms go to triage with it; a clinician then approves the request. */
  book(slotId: number, request: { assessmentId?: number; symptoms?: string }): Promise<ApiResult<Appointment>>
  approve(appointmentId: number): Promise<ApiResult<Appointment>>
  decline(appointmentId: number, reason: string): Promise<ApiResult<Appointment>>
  myAppointments(): Promise<ApiResult<MyAppointment[]>>
  /** Calls onAppointments with the patient's appointments on connect and after every change
   *  (e.g. a clinician's offer). Returns unsubscribe. */
  subscribeMyAppointments(onAppointments: (appointments: MyAppointment[]) => void, onStatus: (s: StreamStatus) => void): () => void
  submitIntake(appointmentId: number, symptoms: string): Promise<ApiResult<TriageRecord>>
  getQueue(): Promise<ApiResult<QueueEntry[]>>
  /** Calls onQueue with the full queue on connect and after every change. Returns unsubscribe. */
  subscribeQueue(onQueue: (queue: QueueEntry[]) => void, onStatus: (s: StreamStatus) => void): () => void
  review(triageId: number, finalUrgency: Urgency): Promise<ApiResult<TriageRecord>>
  uploadLabReport(appointmentId: number, file: File, details?: { examType?: ExamType; takenOn?: string }): Promise<ApiResult<LabReport>>
  labWorklist(date: string): Promise<ApiResult<LabWorklistEntry[]>>
  uploadLabReportAsTech(appointmentId: number, file: File, details?: { examType?: ExamType; requestId?: number }): Promise<ApiResult<LabReport>>
  /** Clinical staff ask the lab for a test, with an urgency and a note for the lab */
  requestLab(appointmentId: number, examType: ExamType, urgency: Urgency, note: string): Promise<ApiResult<LabRequestSummary>>
  /** Lab technician: open requests (most urgent first) or recently done ones */
  labRequests(state: 'open' | 'done'): Promise<ApiResult<LabRequestEntry[]>>
  updateLabRequest(requestId: number, status: 'scheduled' | 'cancelled'): Promise<ApiResult<LabRequestSummary>>
  /** Lab technician: free lab times for a request, and proposing one to three to the patient */
  labTimes(requestId: number): Promise<ApiResult<LabTimes>>
  proposeLabTimes(requestId: number, times: string[]): Promise<ApiResult<LabRequestSummary>>
  /** Patient: free lab times they may choose, and booking one (proposed or their own) */
  myLabTimes(requestId: number): Promise<ApiResult<LabTimes>>
  scheduleLabVisit(requestId: number, startsAt: string): Promise<ApiResult<LabRequestSummary>>
  /** Physician: their own upcoming visits, then those completed in the last two weeks */
  physicianSchedule(): Promise<ApiResult<QueueEntry[]>>
  completeVisit(appointmentId: number, summary: string): Promise<ApiResult<Appointment>>
  providers(): Promise<ApiResult<Provider[]>>
  adminUsers(): Promise<ApiResult<AdminUser[]>>
  updateUser(userId: number, role: Role, providerId: number | null, active?: boolean): Promise<ApiResult<AdminUser>>
  invite(email: string, role: Role, providerId: number | null): Promise<ApiResult<Invitation>>
  invitations(): Promise<ApiResult<Invitation[]>>
  revokeInvitation(invitationId: number): Promise<ApiResult<Invitation>>
  /** No sign-in needed: the link is the secret */
  viewInvitation(token: string): Promise<ApiResult<InvitationView>>
  acceptInvitation(token: string): Promise<ApiResult<{ access_token: string; user: User }>>
  labReports(appointmentId: number): Promise<ApiResult<LabReport[]>>
  approveLabExplanation(reportId: number, text: string): Promise<ApiResult<LabReport>>
  /** The original file (clinicians), for checking extracted values against it */
  labReportFile(reportId: number): Promise<ApiResult<Blob>>
  /** How a priority is decided and how soon each priority should be seen */
  urgencyMatrix(): Promise<ApiResult<UrgencyMatrix>>
  /** Free times in the next withinHours, earliest first (booking by timeframe) */
  earliestSlots(withinHours: number, providerId?: number, urgent?: boolean): Promise<ApiResult<Slot[]>>
  /** The first free time after a timeframe, for when nothing is free inside it (null if none) */
  nextAvailable(afterHours: number, providerId?: number, urgent?: boolean): Promise<ApiResult<Slot | null>>
  /** Times this visit can move to; withinHours defaults to the longest the priority allows */
  scheduleOptions(appointmentId: number, withinHours?: number): Promise<ApiResult<ScheduleOptions>>
  /** The patient accepts a new time; the intake and lab reports move with the visit */
  reschedule(appointmentId: number, slotId: number): Promise<ApiResult<MyAppointment>>
  /** Clinician: free earlier slots with the same provider */
  earlierSlots(appointmentId: number): Promise<ApiResult<Slot[]>>
  offerEarlierVisit(appointmentId: number, slotId: number): Promise<ApiResult<RescheduleOffer>>
  /** Times the clinician may propose: free, any doctor, within the patient's priority */
  alternativeSlots(appointmentId: number): Promise<ApiResult<Slot[]>>
  /** Propose one to three times; they replace any proposed before */
  propose(appointmentId: number, slotIds: number[]): Promise<ApiResult<RescheduleOffer[]>>
  acceptOffer(offerId: number): Promise<ApiResult<MyAppointment>>
  /** None of the proposed times work: declines them all, with an optional note for the clinician */
  declineOffer(offerId: number, note?: string): Promise<ApiResult<{ id: number; status: string }>>
}
