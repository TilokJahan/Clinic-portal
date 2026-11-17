import { endSession, sessionToken as getToken } from '../session'
import type { Api, ApiResult, StreamStatus } from '../types'

// The appointment service, reached through the dev-server proxy or nginx (see vite.config.ts and
// nginx.conf), so the browser never needs CORS.
const BASE = import.meta.env.VITE_API_BASE ?? '/api'

function describe(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return 'Please check the form and try again.' // 422 validation list
  return `Request failed (${status})`
}

async function send(path: string, init?: RequestInit, json = true): Promise<Response | null> {
  try {
    const token = await getToken()
    return await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(json ? { 'Content-Type': 'application/json' } : {}), // FormData sets its own type
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    })
  } catch {
    return null
  }
}

const unreachable = { ok: false as const, status: 0, detail: 'Cannot reach the clinic server. Please try again.' }

async function request<T>(path: string, init?: RequestInit, json = true): Promise<ApiResult<T>> {
  const response = await send(path, init, json)
  if (!response) return unreachable
  const body = await response.json().catch(() => null)
  if (response.status === 401) endSession() // expired or revoked: back to the sign-in page
  if (!response.ok) return { ok: false, status: response.status, detail: describe(body?.detail, response.status) }
  return { ok: true, data: body as T }
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

/** Server-Sent Events with reconnects. EventSource can't send headers, so the token goes in the
 *  URL (only for stream endpoints). On error we reconnect with a fresh token, since Entra ID
 *  tokens expire after about an hour. Returns unsubscribe. */
function subscribe<T>(path: string, event: string, onData: (data: T) => void, onStatus: (s: StreamStatus) => void): () => void {
  let source: EventSource | null = null
  let closed = false
  let retry: ReturnType<typeof setTimeout> | undefined
  async function connect() {
    onStatus(source ? 'reconnecting' : 'connecting')
    const token = await getToken()
    if (closed) return
    source = new EventSource(`${BASE}${path}?access_token=${encodeURIComponent(token ?? '')}`)
    source.addEventListener(event, (e) => onData(JSON.parse((e as MessageEvent).data)))
    source.onopen = () => onStatus('live')
    source.onerror = async () => {
      source?.close()
      onStatus('reconnecting')
      // EventSource hides the status code. Ask /me: a 401 there ends the session (see request)
      const me = await request('/me')
      if (!closed && (me.ok || me.status !== 401)) retry = setTimeout(connect, 3000)
    }
  }
  void connect()
  return () => { closed = true; clearTimeout(retry); source?.close() }
}

export const httpApi: Api = {
  getSlots(date, providerId, options) {
    const params = new URLSearchParams({ date })
    if (providerId) params.set('provider_id', String(providerId))
    if (options?.includeBooked) params.set('include_booked', 'true')
    if (options?.urgent) params.set('urgent', 'true')
    return request(`/slots?${params}`)
  },
  assess: (symptoms) => request('/assessments', json('POST', { symptoms })),
  timeframeAvailability: (priority) => request(`/slots/timeframes${priority ? `?priority=${priority}` : ''}`),
  book: (slotId, { assessmentId, symptoms }) =>
    request('/appointments', json('POST', { slot_id: slotId, assessment_id: assessmentId, symptoms })),
  approve: (appointmentId) => request(`/appointments/${appointmentId}/approve`, { method: 'POST' }),
  decline: (appointmentId, reason) =>
    request(`/appointments/${appointmentId}/decline`, json('POST', { reason: reason || null })),
  myAppointments: () => request('/appointments'),
  submitIntake: (appointmentId, symptoms) =>
    request('/intake', json('POST', { appointment_id: appointmentId, symptoms })),
  getQueue: () => request('/queue'),
  subscribeQueue: (onQueue, onStatus) => subscribe('/queue/stream', 'queue', onQueue, onStatus),
  subscribeMyAppointments: (onAppointments, onStatus) =>
    subscribe('/appointments/stream', 'appointments', onAppointments, onStatus),
  review: (triageId, finalUrgency) => request(`/triage/${triageId}`, json('PATCH', { final_urgency: finalUrgency })),
  uploadLabReport(appointmentId, file) {
    const form = new FormData()
    form.append('file', file)
    return request(`/appointments/${appointmentId}/lab-reports`, { method: 'POST', body: form }, false)
  },
  labWorklist: (date) => request(`/lab/worklist?${new URLSearchParams({ date })}`),
  uploadLabReportAsTech(appointmentId, file) {
    const form = new FormData()
    form.append('file', file)
    return request(`/lab/appointments/${appointmentId}/reports`, { method: 'POST', body: form }, false)
  },
  labReports: (appointmentId) => request(`/appointments/${appointmentId}/lab-reports`),
  approveLabExplanation: (reportId, text) =>
    request(`/lab-reports/${reportId}`, json('PATCH', { patient_explanation: text })),
  urgencyMatrix: () => request('/urgency-matrix'),
  earliestSlots(withinHours, providerId, urgent) {
    const params = new URLSearchParams({ within_hours: String(withinHours) })
    if (providerId) params.set('provider_id', String(providerId))
    if (urgent) params.set('urgent', 'true')
    return request(`/slots/earliest?${params}`)
  },
  nextAvailable(afterHours, providerId, urgent) {
    const params = new URLSearchParams({ after_hours: String(afterHours) })
    if (providerId) params.set('provider_id', String(providerId))
    if (urgent) params.set('urgent', 'true')
    return request(`/slots/next-available?${params}`)
  },
  scheduleOptions(appointmentId, withinHours) {
    const params = withinHours ? `?${new URLSearchParams({ within_hours: String(withinHours) })}` : ''
    return request(`/appointments/${appointmentId}/schedule-options${params}`)
  },
  reschedule: (appointmentId, slotId) =>
    request(`/appointments/${appointmentId}/reschedule`, json('POST', { slot_id: slotId })),
  earlierSlots: (appointmentId) => request(`/appointments/${appointmentId}/earlier-slots`),
  offerEarlierVisit: (appointmentId, slotId) =>
    request(`/appointments/${appointmentId}/reschedule-offers`, json('POST', { slot_id: slotId })),
  acceptOffer: (offerId) => request(`/reschedule-offers/${offerId}/accept`, { method: 'POST' }),
  declineOffer: (offerId, note) => request(`/reschedule-offers/${offerId}/decline`, json('POST', { note: note || null })),
  alternativeSlots: (appointmentId) => request(`/appointments/${appointmentId}/alternative-slots`),
  propose: (appointmentId, slotIds) =>
    request(`/appointments/${appointmentId}/proposals`, json('POST', { slot_ids: slotIds })),
  async labReportFile(reportId) {
    const response = await send(`/lab-reports/${reportId}/file`, undefined, false)
    if (!response) return unreachable
    if (response.status === 401) endSession()
    if (!response.ok) return { ok: false, status: response.status, detail: `Request failed (${response.status})` }
    return { ok: true, data: await response.blob() }
  },
}
