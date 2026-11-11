import { sessionUser } from '../session'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import type { Api, ApiResult, Appointment, LabReport, LabWorklistEntry, MyAppointment, QueueEntry, Slot, StreamStatus, TriageRecord, Urgency } from '../types'

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
      return { ...e, lab, urgency: decidedAfterLab ? t!.final_urgency : highest }
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
    return ok(slotsFor(date).filter((s) => !booked.has(s.id) && Date.parse(s.starts_at) > now && (!providerId || s.provider_id === providerId)))
  },
  async book(slotId) {
    await pause(400)
    const patientId = mockPatientId()
    const slot = slots.get(slotId)
    if (!slot) return fail(404, 'Slot not found')
    if (Date.parse(slot.starts_at) <= Date.now()) return fail(409, 'Slot has already started')
    if (takenByOthers.has(slotId) || appointments.some((a) => a.slot_id === slotId && a.status !== 'cancelled'))
      return fail(409, 'Slot is already booked')
    const appt: Appointment = { id: nextId++, patient_id: patientId, slot_id: slotId, status: 'booked', created_at: new Date().toISOString() }
    appointments.push(appt)
    notify()
    return ok(appt)
  },
  async myAppointments() {
    await pause(150)
    return ok(appointments
      .filter((a) => a.patient_id === mockPatientId() && a.status !== 'cancelled')
      .map((a): MyAppointment => {
        const slot = slots.get(a.slot_id)!
        return { id: a.id, slot_id: a.slot_id, status: a.status, created_at: a.created_at, starts_at: slot.starts_at, provider_name: slot.provider_name, specialty: slot.specialty, intake_submitted: triage.some((t) => t.appointment_id === a.id) }
      })
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
  async review(triageId, finalUrgency) {
    await pause(200)
    const record = triage.find((t) => t.id === triageId)
    if (!record) return fail(404, 'Triage result not found')
    Object.assign(record, { final_urgency: finalUrgency, urgency: finalUrgency, overridden: finalUrgency !== record.ai_urgency, reviewed_at: new Date().toISOString() })
    notify()
    return ok({ ...record })
  },
}
