import type { Api, ApiResult } from '../types'

// The appointment service, reached through the dev-server proxy or nginx (see vite.config.ts and
// nginx.conf), so the browser never needs CORS.
const BASE = import.meta.env.VITE_API_BASE ?? '/api'

function describe(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return 'Please check the form and try again.' // 422 validation list
  return `Request failed (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    return { ok: false, status: 0, detail: 'Cannot reach the clinic server. Please try again.' }
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) return { ok: false, status: response.status, detail: describe(body?.detail, response.status) }
  return { ok: true, data: body as T }
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export const httpApi: Api = {
  getSlots(date, providerId) {
    const params = new URLSearchParams({ date })
    if (providerId) params.set('provider_id', String(providerId))
    return request(`/slots?${params}`)
  },
  book: (patientId, slotId) => request('/appointments', json('POST', { patient_id: patientId, slot_id: slotId })),
  submitIntake: (appointmentId, symptoms) =>
    request('/intake', json('POST', { appointment_id: appointmentId, symptoms })),
  getQueue: () => request('/queue'),
  subscribeQueue(onQueue, onStatus) {
    onStatus('connecting')
    const source = new EventSource(`${BASE}/queue/stream`)
    source.addEventListener('queue', (event) => onQueue(JSON.parse((event as MessageEvent).data)))
    source.onopen = () => onStatus('live')
    source.onerror = () => onStatus('reconnecting') // EventSource retries by itself
    return () => source.close()
  },
  review: (triageId, finalUrgency) => request(`/triage/${triageId}`, json('PATCH', { final_urgency: finalUrgency })),
}
