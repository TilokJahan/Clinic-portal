import { useCallback, useEffect, useState } from 'react'
import { currentToken, signOutEverywhere, type Session } from './auth'

// The signed-in session. It lives in this module (and localStorage, so a reload doesn't sign you
// out) rather than only in React state, so the API client can read the token synchronously at
// any time: pages fetch in their own effects, which can run before any parent effect.

const KEY = 'clinic-portal.session'

function read(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

let active: Session | null = read()
const listeners = new Set<(s: Session | null) => void>()

function setActive(next: Session | null) {
  active = next
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next))
    else localStorage.removeItem(KEY)
  } catch {
    // Storage blocked (private window): the session lasts until reload
  }
  listeners.forEach((l) => l(next))
}

/** The signed-in user (used by the mock API, which has no tokens). */
export const sessionUser = () => active?.user ?? null

/** Token for the next API call, or null when signed out. */
export const sessionToken = () => currentToken(active)

/** Called by the API client on a 401: the token expired or was revoked. */
export function endSession() {
  if (!active) return
  void signOutEverywhere()
  setActive(null)
}

export function useSession() {
  const [session, setState] = useState<Session | null>(active)
  useEffect(() => {
    listeners.add(setState)
    return () => { listeners.delete(setState) }
  }, [])
  const setSession = useCallback((next: Session | null) => setActive(next), [])
  return { session, setSession, signOut: endSession }
}
