import type { QueueEntry } from './types'

// Display helpers. The API sends UTC ISO strings; everything is shown in the viewer's time zone.

/** Short zone name in effect at that moment, e.g. "EDT" before and "EST" after daylight saving ends. */
export const timeZoneName = (at: Date | string = new Date()) =>
  new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date(at)).find((p) => p.type === 'timeZoneName')?.value ?? 'local time'

export const formatTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

export const formatDay = (iso: string) =>
  new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })

export const formatDateTime = (iso: string) => `${formatDay(iso)}, ${formatTime(iso)} ${timeZoneName(iso)}`

export const todayLong = () =>
  new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).toUpperCase()

/** Minutes the patient has been waiting since submitting their intake (or booking, if none). */
export const waitMinutes = (entry: QueueEntry, now = Date.now()) =>
  Math.max(0, Math.round((now - Date.parse(entry.triage?.created_at ?? entry.booked_at)) / 60_000))

export const formatWait = (minutes: number) =>
  minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`

/** "Patient 0042" -> "42" for the avatar circle. */
export const initials = (label: string) => String(Number(label.replace(/\D/g, '')) || '?')

/** Local YYYY-MM-DD for <input type="date">, starting from the next weekday. */
export function nextWeekday(from = new Date()): string {
  const d = new Date(from)
  do d.setDate(d.getDate() + 1); while (d.getDay() === 0 || d.getDay() === 6)
  return d.toLocaleDateString('en-CA') // en-CA formats as YYYY-MM-DD
}

export const todayInput = () => new Date().toLocaleDateString('en-CA')
