import type { Api, ApiResult, Appointment, QueueEntry, Slot, StreamStatus, TriageRecord, Urgency } from '../types'

// In-memory stand-in for the appointment service, shaped exactly like docs/api.md.
// Synthetic data only. Used by `npm run dev`; `npm run dev:api` talks to the real backend.

const PROVIDERS = [
  { id: 1, name: 'Dr. Alex Example', specialty: 'General Practice' },
  { id: 2, name: 'Dr. Sam Sample', specialty: 'Dermatology' },
  { id: 3, name: 'Dr. Jordan Test', specialty: 'Cardiology' },
]
const PATIENT_IDS = [1, 2, 3]

const pause = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))
const ok = <T>(data: T): ApiResult<T> => ({ ok: true, data })
const fail = (status: number, detail: string): ApiResult<never> => ({ ok: false, status, detail })
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()

const slots = new Map<number, Slot>()
const slotByKey = new Map<string, number>()
const appointments: Appointment[] = []
const triage: TriageRecord[] = []
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
        const starts = new Date(day.getTime() + (9 * 60 + i * 30) * 60_000)
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
      }
    })
    .sort((x, y) => {
      const ux = x.triage ? ORDER[x.triage.urgency] : 3, uy = y.triage ? ORDER[y.triage.urgency] : 3
      if (ux !== uy) return ux - uy
      if (x.triage && y.triage) return x.triage.created_at.localeCompare(y.triage.created_at)
      return x.starts_at.localeCompare(y.starts_at)
    })
}

const notify = () => listeners.forEach((l) => l(queue()))

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
  async book(patientId, slotId) {
    await pause(400)
    const slot = slots.get(slotId)
    if (!slot) return fail(404, 'Slot not found')
    if (!PATIENT_IDS.includes(patientId)) return fail(404, 'Patient not found')
    if (Date.parse(slot.starts_at) <= Date.now()) return fail(409, 'Slot has already started')
    if (takenByOthers.has(slotId) || appointments.some((a) => a.slot_id === slotId && a.status !== 'cancelled'))
      return fail(409, 'Slot is already booked')
    const appt: Appointment = { id: nextId++, patient_id: patientId, slot_id: slotId, status: 'booked', created_at: new Date().toISOString() }
    appointments.push(appt)
    notify()
    return ok(appt)
  },
  async submitIntake(appointmentId, symptoms) {
    await pause(600)
    const appt = appointments.find((a) => a.id === appointmentId)
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
  async review(triageId, finalUrgency) {
    await pause(200)
    const record = triage.find((t) => t.id === triageId)
    if (!record) return fail(404, 'Triage result not found')
    Object.assign(record, { final_urgency: finalUrgency, urgency: finalUrgency, overridden: finalUrgency !== record.ai_urgency, reviewed_at: new Date().toISOString() })
    notify()
    return ok({ ...record })
  },
}
