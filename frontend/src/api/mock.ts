import { sessionUser } from '../session'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import type { Api, ApiResult, Appointment, PendingOffer, RescheduleOffer, UrgencyMatrix, LabReport, LabWorklistEntry, MyAppointment, QueueEntry, Slot, StreamStatus, TriageRecord, Urgency } from '../types'

// In-memory stand-in for the appointment service, shaped exactly like docs/api.md.
// Synthetic data only. Used by `npm run dev`; `npm run dev:api` talks to the real backend.

const PROVIDERS = [
  { id: 1, name: 'Dr. Alex Example', specialty: 'General Practice' },
  { id: 2, name: 'Dr. Sam Sample', specialty: 'Dermatology' },
  { id: 3, name: 'Dr. Jordan Test', specialty: 'Cardiology' },
]
// The mock has no tokens: the patient is whoever is signed in
const mockPatientId = () => sessionUser()?.id ?? 0

const pause = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))
const ok = <T>(data: T): ApiResult<T> => ({ ok: true, data })
const fail = (status: number, detail: string): ApiResult<never> => ({ ok: false, status, detail })
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()

const slots = new Map<number, Slot>()
const slotByKey = new Map<string, number>()
const appointments: Appointment[] = []
const triage: TriageRecord[] = []
const labReports: LabReport[] = []
const labFiles = new Map<number, Blob>()
// The first slot of each day with Dr. Alex Example is "taken by someone else": it is still
// listed, but booking it returns 409, so the conflict message can be demoed.
const takenByOthers = new Set<number>()
let nextId = 1000
const listeners = new Set<(q: QueueEntry[]) => void>()
const offers: { id: number; appointment_id: number; slot_id: number; status: RescheduleOffer['status']; created_at: string }[] = []

// Mirrors app/urgency.py (GET /urgency-matrix)
const MATRIX: UrgencyMatrix = {
  levels: [
    { urgency: 'urgent', seen_within_hours: 24, seen_within: 'Within 24 hours',
      symptom_signals: ['A red-flag rule matches: chest pain or pressure, trouble breathing, stroke signs, fainting, severe bleeding, allergic swelling, worst-ever headache, or self-harm risk', 'The AI judges the symptoms urgent', 'The AI’s safety filter refused the message (treated as urgent until a clinician reads it)'],
      lab_signals: ['Any critical value (critical low or critical high)'],
      action: 'Top of the queue. The patient sees an emergency notice and can only choose a visit within 24 hours, including the slots kept free for urgent care; a clinician can offer an earlier slot.' },
    { urgency: 'soon', seen_within_hours: 72, seen_within: 'Within 3 days',
      symptom_signals: ['The AI judges the symptoms new, worsening or needing a check this week', 'The AI could not be reached (safe default until a clinician reviews)'],
      lab_signals: ['Any value outside the reference range (low or high)', 'A report that could not be read'],
      action: 'Ahead of routine patients. The patient chooses a visit within 3 days.' },
    { urgency: 'routine', seen_within_hours: 336, seen_within: 'Within 2 weeks',
      symptom_signals: ['The AI judges the symptoms mild, stable or long-standing'],
      lab_signals: ['All values within the reference range'],
      action: 'Seen in order of arrival. The patient chooses any visit within 2 weeks.' },
  ],
  rules: [
    'The priority is the higher of the symptom priority and the lab priority (see the grid).',
    'Fixed rules decide red flags and critical lab values. The AI can raise a priority but never lower one set by a rule.',
    'A clinician reviews every AI suggestion. A clinician’s decision made after the latest lab result is final.',
    'Patients choose when to come within the time allowed for their priority, never later. Nothing is moved until the patient accepts. If nothing is free in time, they can still take any time earlier than their current visit, and the clinician queue flags them.',
    'Each provider keeps the last slot of the day free for urgent patients. If no urgent patient needs it, it opens to everyone 2 hours before it starts.',
  ],
  timeframes: [
    { hours: 24, label: 'Within 24 hours' }, { hours: 72, label: 'Within 3 days' },
    { hours: 168, label: 'Within 1 week' }, { hours: 336, label: 'Within 2 weeks' },
  ],
}
const limitFor = (u: Urgency | null) => MATRIX.levels.find((l) => l.urgency === u)?.seen_within_hours ?? 336
const limitMessage = (hours: number) =>
  `Your care team needs to see you ${MATRIX.timeframes.find((t) => t.hours === hours)!.label.toLowerCase()}. Please choose an earlier time.`
// The urgent reserve (app/urgency.py): the last slot of each day, opening to everyone 2 hours before
const reservedSlots = new Set<number>()
const RESERVED_MESSAGE = 'That time is kept free for urgent care. Please pick another.'
const reserveClosed = (s: Slot) => reservedSlots.has(s.id) && Date.parse(s.starts_at) > Date.now() + 2 * 3_600_000
const view = (s: Slot): Slot => ({ ...s, reserved: reserveClosed(s) })
const isActive = (slotId: number) => takenByOthers.has(slotId) || appointments.some((a) => a.slot_id === slotId && a.status !== 'cancelled')

/** Free, upcoming slots starting after `afterHours` and within `hours`, earliest first. Only urgent
 * patients (and clinicians) see the urgent reserve. */
function freeSlotsWithin(hours: number, providerId?: number, limit = 12, urgent = false, afterHours = 0): Slot[] {
  const now = Date.now(), start = now + afterHours * 3_600_000, end = now + hours * 3_600_000
  const days = new Set<string>()
  for (let t = now; t <= end + 86_400_000; t += 86_400_000) days.add(new Date(t).toISOString().slice(0, 10))
  return [...days].flatMap(slotsFor)
    .filter((s) => { const at = Date.parse(s.starts_at); return at > start && at <= end && !isActive(s.id) && (urgent || !reserveClosed(s)) && (!providerId || s.provider_id === providerId) })
    .sort((x, y) => x.starts_at.localeCompare(y.starts_at) || x.provider_id - y.provider_id)
    .slice(0, limit)
    .map(view)
}

/** The first free time after `afterHours` (the mock schedule goes 4 weeks ahead). */
const nextFree = (afterHours: number, providerId?: number, urgent = false) =>
  freeSlotsWithin(28 * 24, providerId, 1, urgent, afterHours)[0] ?? null

const LATEST_VISIT_HOURS: Partial<Record<Urgency, number>> = { urgent: 24, soon: 72 }

/** An offer the patient can still act on: pending, slot not started and still free. */
const liveOffer = (appointmentId: number) => offers.find((o) => o.appointment_id === appointmentId && o.status === 'pending'
  && Date.parse(slots.get(o.slot_id)!.starts_at) > Date.now() && !isActive(o.slot_id))

/** Book the slot, move the intake and lab reports over, cancel the old visit (app/reschedule.py). */
function moveBooking(old: Appointment, slotId: number): Appointment {
  const moved: Appointment = { id: nextId++, patient_id: old.patient_id, slot_id: slotId, status: 'booked', created_at: new Date().toISOString() }
  appointments.push(moved)
  triage.filter((t) => t.appointment_id === old.id).forEach((t) => { t.appointment_id = moved.id })
  labReports.filter((r) => r.appointment_id === old.id).forEach((r) => { r.appointment_id = moved.id })
  offers.filter((o) => o.appointment_id === old.id && o.status === 'pending').forEach((o) => { o.status = 'expired' })
  old.status = 'cancelled'
  return moved
}

function slotsFor(date: string): Slot[] {
  const day = new Date(`${date}T00:00:00Z`)
  if ([0, 6].includes(day.getUTCDay())) return []
  const result: Slot[] = []
  for (const p of PROVIDERS) {
    for (let i = 0; i < 6; i++) {
      const key = `${date}/${p.id}/${i}`
      let id = slotByKey.get(key)
      if (id === undefined) {
        id = nextId++
        const starts = new Date(day.getTime() + (14 * 60 + i * 30) * 60_000)
        slots.set(id, {
          id, provider_id: p.id, provider_name: p.name, specialty: p.specialty,
          starts_at: starts.toISOString(), ends_at: new Date(starts.getTime() + 30 * 60_000).toISOString(),
        })
        slotByKey.set(key, id)
        if (p.id === 1 && i === 0) takenByOthers.add(id)
        if (i === 5) reservedSlots.add(id)
      }
      result.push(slots.get(id)!)
    }
  }
  return result
}

function fakeTriage(symptoms: string): Pick<TriageRecord, 'ai_urgency' | 'suggested_specialty' | 'red_flags' | 'summary'> {
  const text = symptoms.toLowerCase()
  if (['chest pain', "can't breathe", 'unconscious'].some((w) => text.includes(w)))
    return { ai_urgency: 'urgent', suggested_specialty: 'Emergency Medicine', red_flags: ['possible cardiac or respiratory emergency'], summary: 'Potentially serious symptom reported. Clinician review needed now.' }
  return { ai_urgency: 'routine', suggested_specialty: 'General Practice', red_flags: [], summary: 'No red-flag symptoms detected in the intake text.' }
}

function addTriage(appointmentId: number, t: ReturnType<typeof fakeTriage>, createdMinutesAgo = 0): TriageRecord {
  const record: TriageRecord = {
    id: nextId++, appointment_id: appointmentId, ...t, final_urgency: null, urgency: t.ai_urgency,
    overridden: false, latency_ms: 40, created_at: minutesAgo(createdMinutesAgo), reviewed_at: null,
  }
  triage.push(record)
  return record
}

const ORDER: Record<Urgency, number> = { urgent: 0, soon: 1, routine: 2 }

function queue(): QueueEntry[] {
  return appointments
    .filter((a) => a.status === 'booked' || a.status === 'checked_in')
    .map((a) => {
      const slot = slots.get(a.slot_id)!
      return {
        appointment_id: a.id, patient_label: `Patient ${String(a.patient_id).padStart(4, '0')}`,
        provider_id: slot.provider_id, provider_name: slot.provider_name, starts_at: slot.starts_at,
        status: a.status, booked_at: a.created_at, triage: triage.find((t) => t.appointment_id === a.id) ?? null,
        lab: null, urgency: null,
      } as QueueEntry
    })
    .map((e) => {
      const report = labReports.filter((r) => r.appointment_id === e.appointment_id).slice(-1)[0]
      const lab = report ? { report_id: report.id, status: report.status, urgency: report.lab_urgency, reason: report.reason, explanation_approved: report.explanation_approved } : null
      const t = e.triage
      const decidedAfterLab = t?.reviewed_at && (!report?.processed_at || t.reviewed_at >= report.processed_at)
      const candidates = [t?.urgency, lab?.urgency].filter(Boolean) as Urgency[]
      const highest = candidates.sort((x, y) => ORDER[x] - ORDER[y])[0] ?? null
      const urgency = decidedAfterLab ? t!.final_urgency : highest
      const offerPending = Boolean(liveOffer(e.appointment_id))
      const latest = urgency ? LATEST_VISIT_HOURS[urgency] : undefined
      const needsEarlier = e.status === 'booked' && latest !== undefined && !offerPending && Date.parse(e.starts_at) > Date.now() + latest * 3_600_000
      return { ...e, lab, urgency, needs_earlier_visit: needsEarlier, offer_pending: offerPending }
    })
    .sort((x, y) => {
      const ux = x.urgency ? ORDER[x.urgency] : 3, uy = y.urgency ? ORDER[y.urgency] : 3
      if (ux !== uy) return ux - uy
      if (x.triage && y.triage) return x.triage.created_at.localeCompare(y.triage.created_at)
      return x.starts_at.localeCompare(y.starts_at)
    })
}

const notify = () => listeners.forEach((l) => l(queue()))

/** What a patient may see: nothing but the status until a clinician approves. */
function patientView(r: LabReport): LabReport {
  if (!r.explanation_approved) return { ...r, lab_urgency: null, reason: null, clinician_summary: null, patient_explanation: null, extraction_confidence: null, results: [] }
  return { ...r, clinician_summary: null, reason: null }
}

async function acceptLabUpload(appointmentId: number, file: File, ownOnly: boolean): Promise<ApiResult<LabReport>> {
  await pause(500)
  const user = sessionUser()
  if (!user) return fail(401, 'Sign in to upload a report')
  if (ownOnly ? user.role !== 'patient' : !['lab_tech', 'admin'].includes(user.role)) return fail(403, 'Not allowed for your role')
  const appt = appointments.find((a) => a.id === appointmentId && (!ownOnly || a.patient_id === user.id))
  if (!appt) return fail(404, 'Appointment not found')
  if (appt.status === 'cancelled') return fail(409, 'Appointment is cancelled')
  if (!ownOnly && appt.status !== 'booked' && appt.status !== 'checked_in') return fail(409, 'Appointment is already completed')
  const problem = labFileError(file)
  if (problem) return fail(!LAB_FILE_ACCEPT.split(',').includes(file.type) ? 415 : file.size === 0 ? 422 : 413, problem)
    // The mock "reads" every report as the synthetic critical-potassium example
    const completed: LabReport = {
      id: nextId++, appointment_id: appointmentId, content_type: file.type, status: 'ready',
      uploaded_at: new Date().toISOString(), processed_at: new Date().toISOString(),
      lab_urgency: 'urgent', reason: 'Critical: potassium 6.8 mmol/L',
      clinician_summary: 'Potassium critically high at 6.8 mmol/L; creatinine mildly raised. Other results in range.',
      patient_explanation: 'We checked the salts and kidney markers in your blood. Your potassium was higher than the usual range, and one kidney marker was a little high. Your care team will contact you today about next steps.',
      explanation_approved: false, explanation_approved_at: null, extraction_confidence: 0.97,
      results: [
        { display_name: 'Potassium', test_name: 'Potassium', canonical: 'potassium', value: 6.8, unit: 'mmol/L', ref_low: 3.5, ref_high: 5.1, flag: 'critical_high', confidence: 0.98, needs_verification: false, verification_reason: null },
        { display_name: 'Creatinine', test_name: 'Creatinine', canonical: 'creatinine', value: 1.9, unit: 'mg/dL', ref_low: 0.6, ref_high: 1.2, flag: 'high', confidence: 0.97, needs_verification: false, verification_reason: null },
        { display_name: 'Sodium', test_name: 'Sodium', canonical: 'sodium', value: 136, unit: 'mmol/L', ref_low: 135, ref_high: 145, flag: 'normal', confidence: 0.99, needs_verification: false, verification_reason: null },
      ],
    }
  const report: LabReport = { ...completed, status: 'processing', processed_at: null, results: [], lab_urgency: null,
    reason: null, clinician_summary: null, patient_explanation: null, extraction_confidence: null }
  labReports.push(report)
  labFiles.set(report.id, file)
  setTimeout(() => {
    Object.assign(report, completed, { processed_at: new Date().toISOString() })
    notify()
  }, 800)
  notify()
  return ok(patientView(report))
}

function pendingOfferFor(appointmentId: number): PendingOffer | null {
  const offer = liveOffer(appointmentId)
  if (!offer) return null
  const slot = slots.get(offer.slot_id)!
  return { id: offer.id, slot_id: slot.id, starts_at: slot.starts_at, provider_name: slot.provider_name }
}

function myView(id: number): MyAppointment {
  const a = appointments.find((x) => x.id === id)!, slot = slots.get(a.slot_id)!
  return { id: a.id, slot_id: a.slot_id, status: a.status, created_at: a.created_at, starts_at: slot.starts_at, provider_name: slot.provider_name,
    specialty: slot.specialty, intake_submitted: triage.some((t) => t.appointment_id === a.id), pending_offer: pendingOfferFor(a.id) }
}

// Seed a few waiting patients for the clinician screens
;(function seed() {
  const today = new Date()
  do today.setUTCDate(today.getUTCDate() + 1); while ([0, 6].includes(today.getUTCDay()))
  const day = slotsFor(today.toISOString().slice(0, 10))
  const seeds: [number, number, ReturnType<typeof fakeTriage> | null, number][] = [
    [1, 7, { ai_urgency: 'urgent', suggested_specialty: 'Cardiology', red_flags: ['chest discomfort', 'shortness of breath'], summary: 'Chest tightness and shortness of breath since this morning, worse with activity.' }, 6],
    [2, 13, { ai_urgency: 'soon', suggested_specialty: 'General Practice', red_flags: ['fever for 3 days'], summary: 'Fever and dry cough for three days with fatigue. Drinking fluids.' }, 14],
    [3, 2, { ai_urgency: 'routine', suggested_specialty: 'Dermatology', red_flags: [], summary: 'Itchy dry patch on the elbow for a month, not spreading.' }, 25],
    [1, 8, null, 0],
  ]
  for (const [patient, slotIndex, t, mins] of seeds) {
    const appt: Appointment = { id: nextId++, patient_id: patient, slot_id: day[slotIndex].id, status: 'booked', created_at: minutesAgo(mins + 30) }
    appointments.push(appt)
    if (t) addTriage(appt.id, t, mins)
  }
})()

export const mockApi: Api = {
  async getSlots(date, providerId) {
    await pause(150)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return fail(422, 'Please choose a valid date.')
    const now = Date.now()
    const booked = new Set(appointments.filter((a) => a.status !== 'cancelled').map((a) => a.slot_id))
    return ok(slotsFor(date).filter((s) => !booked.has(s.id) && !takenByOthers.has(s.id) && !reserveClosed(s) && Date.parse(s.starts_at) > now && (!providerId || s.provider_id === providerId)).map(view))
  },
  async book(slotId) {
    await pause(400)
    const patientId = mockPatientId()
    const slot = slots.get(slotId)
    if (!slot) return fail(404, 'Slot not found')
    if (Date.parse(slot.starts_at) <= Date.now()) return fail(409, 'Slot has already started')
    if (takenByOthers.has(slotId) || appointments.some((a) => a.slot_id === slotId && a.status !== 'cancelled'))
      return fail(409, 'Slot is already booked')
    if (reserveClosed(slot)) return fail(409, RESERVED_MESSAGE)
    const appt: Appointment = { id: nextId++, patient_id: patientId, slot_id: slotId, status: 'booked', created_at: new Date().toISOString() }
    appointments.push(appt)
    notify()
    return ok(appt)
  },
  async myAppointments() {
    await pause(150)
    return ok(appointments
      .filter((a) => a.patient_id === mockPatientId() && a.status !== 'cancelled')
      .map((a) => myView(a.id))
      .sort((x, y) => x.starts_at.localeCompare(y.starts_at)))
  },
  async submitIntake(appointmentId, symptoms) {
    await pause(600)
    const appt = appointments.find((a) => a.id === appointmentId && a.patient_id === mockPatientId())
    if (!appt) return fail(404, 'Appointment not found')
    if (appt.status === 'cancelled') return fail(409, 'Appointment is cancelled')
    if (triage.some((t) => t.appointment_id === appointmentId)) return fail(409, 'Intake already submitted')
    if (!symptoms.trim() || symptoms.length > 4000) return fail(422, 'Please check the form and try again.')
    const record = addTriage(appointmentId, fakeTriage(symptoms))
    notify()
    return ok(record)
  },
  async getQueue() { await pause(); return ok(queue()) },
  subscribeQueue(onQueue, onStatus: (s: StreamStatus) => void) {
    listeners.add(onQueue)
    onStatus('live')
    setTimeout(() => onQueue(queue()), 0)
    return () => { listeners.delete(onQueue) }
  },
  uploadLabReport: (appointmentId, file) => acceptLabUpload(appointmentId, file, true),
  uploadLabReportAsTech: (appointmentId, file) => acceptLabUpload(appointmentId, file, false),
  async labWorklist(date) {
    await pause(150)
    const user = sessionUser()
    if (!user) return fail(401, 'Sign in to view scheduled visits')
    if (user.role !== 'lab_tech' && user.role !== 'admin') return fail(403, 'Not allowed for your role')
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(`${date}T00:00:00Z`))) return fail(422, 'Please choose a valid date.')
    return ok(appointments
      .filter((a) => (a.status === 'booked' || a.status === 'checked_in') && slots.get(a.slot_id)!.starts_at.slice(0, 10) === date)
      .map((a): LabWorklistEntry => {
        const slot = slots.get(a.slot_id)!
        return { appointment_id: a.id, patient_label: `Patient ${String(a.patient_id).padStart(4, '0')}`,
          starts_at: slot.starts_at, provider_name: slot.provider_name, status: a.status as LabWorklistEntry['status'],
          reports: labReports.filter((r) => r.appointment_id === a.id)
            .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at) || b.id - a.id)
            .map(({ id, status, uploaded_at, lab_urgency, reason }) => ({ id, status, uploaded_at, lab_urgency, reason })) }
      })
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.appointment_id - b.appointment_id))
  },
  async labReports(appointmentId) {
    await pause(150)
    const user = sessionUser()
    if (!user) return fail(401, 'Sign in to view reports')
    if (user.role === 'lab_tech') return fail(403, 'Not allowed for your role')
    const appointment = appointments.find((a) => a.id === appointmentId)
    if (!appointment || (user.role === 'patient' && appointment.patient_id !== user.id)) return fail(404, 'Appointment not found')
    const own = user.role === 'patient'
    const reports = labReports.filter((r) => r.appointment_id === appointmentId).reverse()
    return ok(own ? reports.map(patientView) : reports.map((r) => ({ ...r })))
  },
  async approveLabExplanation(reportId, text) {
    await pause(200)
    if (!['clinician', 'admin'].includes(sessionUser()?.role ?? '')) return fail(403, 'Not allowed for your role')
    const report = labReports.find((r) => r.id === reportId)
    if (!report) return fail(404, 'Lab report not found')
    Object.assign(report, { patient_explanation: text, explanation_approved: true, explanation_approved_at: new Date().toISOString() })
    notify()
    return ok({ ...report })
  },
  async labReportFile(reportId) {
    if (!['clinician', 'admin'].includes(sessionUser()?.role ?? '')) return fail(403, 'Not allowed for your role')
    const file = labFiles.get(reportId)
    return file ? ok(file) : fail(404, 'Lab report not found')
  },
  async urgencyMatrix() { await pause(100); return ok(MATRIX) },
  async earliestSlots(withinHours, providerId) {
    await pause(200)
    if (!MATRIX.timeframes.some((t) => t.hours === withinHours)) return fail(422, 'within_hours must be one of 24, 72, 168, 336')
    return ok(freeSlotsWithin(withinHours, providerId))
  },
  async nextAvailable(afterHours, providerId) {
    await pause(150)
    if (!MATRIX.timeframes.some((t) => t.hours === afterHours)) return fail(422, 'after_hours must be one of 24, 72, 168, 336')
    return ok(nextFree(afterHours, providerId))
  },
  async scheduleOptions(appointmentId, withinHours) {
    await pause(200)
    const appt = appointments.find((a) => a.id === appointmentId && a.patient_id === mockPatientId())
    if (!appt) return fail(404, 'Appointment not found')
    if (appt.status !== 'booked') return fail(409, 'Appointment is not booked')
    const priority = triage.find((x) => x.appointment_id === appointmentId)?.urgency ?? null
    const effective = queue().find((e) => e.appointment_id === appointmentId)?.urgency ?? null
    const limit = limitFor(effective), urgent = effective === 'urgent'
    const within = withinHours ?? limit
    if (within > limit) return fail(422, limitMessage(limit))
    const startsAt = slots.get(appt.slot_id)!.starts_at
    const free = freeSlotsWithin(within, undefined, 12, urgent)
    return ok({ appointment_id: appointmentId, starts_at: startsAt, priority, max_within_hours: limit, care_team_limit: limit < limitFor(priority),
      within_hours: within, current_fits: Date.parse(startsAt) <= Date.now() + within * 3_600_000, slots: free,
      next_available: free.length ? null : nextFree(within, undefined, urgent) })
  },
  async reschedule(appointmentId, slotId) {
    await pause(400)
    const appt = appointments.find((a) => a.id === appointmentId && a.patient_id === mockPatientId())
    if (!appt) return fail(404, 'Appointment not found')
    if (appt.status !== 'booked') return fail(409, 'Appointment is not booked')
    const slot = slots.get(slotId)
    if (!slot) return fail(404, 'Slot not found')
    if (Date.parse(slot.starts_at) <= Date.now()) return fail(409, 'Slot has already started')
    const effective = queue().find((e) => e.appointment_id === appointmentId)?.urgency ?? null
    const limit = limitFor(effective)
    // Within the limit, or at least earlier than the current visit
    if (Date.parse(slot.starts_at) > Date.now() + limit * 3_600_000 && slot.starts_at >= slots.get(appt.slot_id)!.starts_at) return fail(422, limitMessage(limit))
    if (reserveClosed(slot) && effective !== 'urgent') return fail(409, RESERVED_MESSAGE)
    if (isActive(slotId)) return fail(409, 'Slot is already booked')
    const moved = moveBooking(appt, slotId)
    notify()
    return ok(myView(moved.id))
  },
  async earlierSlots(appointmentId) {
    await pause(200)
    const appt = appointments.find((a) => a.id === appointmentId)
    if (!appt) return fail(404, 'Appointment not found')
    if (appt.status !== 'booked') return fail(409, 'Appointment is not booked')
    const current = slots.get(appt.slot_id)!
    return ok(freeSlotsWithin(14 * 24, current.provider_id, 50, true).filter((s) => s.starts_at < current.starts_at).slice(0, 10))
  },
  async offerEarlierVisit(appointmentId, slotId) {
    await pause(300)
    const appt = appointments.find((a) => a.id === appointmentId)
    if (!appt) return fail(404, 'Appointment not found')
    if (appt.status !== 'booked') return fail(409, 'Appointment is not booked')
    const slot = slots.get(slotId)
    if (!slot) return fail(404, 'Slot not found')
    if (isActive(slotId)) return fail(409, 'Slot is already booked')
    if (liveOffer(appointmentId)) return fail(409, 'An offer is already pending')
    offers.filter((o) => o.appointment_id === appointmentId && o.status === 'pending').forEach((o) => { o.status = 'expired' })
    const offer = { id: nextId++, appointment_id: appointmentId, slot_id: slotId, status: 'pending' as const, created_at: new Date().toISOString() }
    offers.push(offer)
    notify()
    return ok({ id: offer.id, appointment_id: appointmentId, proposed_slot_id: slotId, provider_name: slot.provider_name, starts_at: slot.starts_at, status: 'pending', reason: null, created_at: offer.created_at })
  },
  async acceptOffer(offerId) {
    await pause(400)
    const offer = offers.find((o) => o.id === offerId)
    const appt = offer && appointments.find((a) => a.id === offer.appointment_id && a.patient_id === mockPatientId())
    if (!offer || !appt) return fail(404, 'Offer not found')
    if (offer.status !== 'pending') return fail(409, 'This offer is no longer available')
    if (isActive(offer.slot_id)) { offer.status = 'expired'; return fail(409, 'That time was just taken') }
    const moved = moveBooking(appt, offer.slot_id)
    offer.status = 'accepted'
    notify()
    return ok(myView(moved.id))
  },
  async declineOffer(offerId) {
    await pause(200)
    const offer = offers.find((o) => o.id === offerId)
    if (!offer || !appointments.some((a) => a.id === offer.appointment_id && a.patient_id === mockPatientId())) return fail(404, 'Offer not found')
    if (offer.status !== 'pending') return fail(409, 'This offer is no longer available')
    offer.status = 'declined'
    notify()
    return ok({ id: offer.id, status: offer.status })
  },
  async review(triageId, finalUrgency) {
    await pause(200)
    const record = triage.find((t) => t.id === triageId)
    if (!record) return fail(404, 'Triage result not found')
    Object.assign(record, { final_urgency: finalUrgency, urgency: finalUrgency, overridden: finalUrgency !== record.ai_urgency, reviewed_at: new Date().toISOString() })
    notify()
    return ok({ ...record })
  },
}
