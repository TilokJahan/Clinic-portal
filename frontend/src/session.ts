import { useEffect, useState } from 'react'

// Prototype sign-in: pick a synthetic demo account from db/seed.sql. No password, nothing sent.
// Replaced by real sign-in (JWT) when auth is built.

export type Role = 'patient' | 'clinician'
export interface Session { role: Role; userId: number; email: string }

export const DEMO_ACCOUNTS: Session[] = [
  { role: 'patient', userId: 1, email: 'patient1@example.com' },
  { role: 'patient', userId: 2, email: 'patient2@example.com' },
  { role: 'patient', userId: 3, email: 'patient3@example.com' },
  { role: 'clinician', userId: 4, email: 'clinician1@example.com' },
]

const KEY = 'clinic-portal.session'
const BOOKINGS_KEY = 'clinic-portal.bookings'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage blocked (private window): the session simply lasts until reload
  }
}

export function useSession() {
  const [session, setSession] = useState<Session | null>(() => read<Session | null>(KEY, null))
  useEffect(() => write(KEY, session), [session])
  return [session, setSession] as const
}

// The API has no "my appointments" endpoint yet, so the patient's bookings are remembered here
// to offer them on the intake page.
export interface Booking { appointmentId: number; patientId: number; startsAt: string; providerName: string }

export function rememberBooking(booking: Booking) {
  write(BOOKINGS_KEY, [booking, ...read<Booking[]>(BOOKINGS_KEY, [])].slice(0, 20))
}

export function bookingsFor(patientId: number): Booking[] {
  return read<Booking[]>(BOOKINGS_KEY, []).filter((b) => b.patientId === patientId)
}
