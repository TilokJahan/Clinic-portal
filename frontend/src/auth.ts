import type { ApiResult, User } from './types'

// Sign-in. Three modes, all ending in a Session with a bearer token:
// - mock: no backend; pick a demo account, the token is a placeholder
// - dev: POST /api/auth/dev-login for a synthetic seed account (backend AUTH_MODE=dev)
// - identity-platform: email + password with Google Identity Platform (Firebase Auth); the ID
//   token is refreshed by the SDK and verified by the backend (AUTH_MODE=identity-platform)

export type AuthMode = 'mock' | 'dev' | 'identity-platform'

export const authMode: AuthMode =
  import.meta.env.VITE_API_MODE !== 'http' ? 'mock'
    : import.meta.env.VITE_AUTH_MODE === 'identity-platform' ? 'identity-platform' : 'dev'

export interface Session { token: string; user: User }

const API = import.meta.env.VITE_API_BASE ?? '/api'

export const DEMO_ACCOUNTS: User[] = [
  { id: 1, email: 'patient1@example.com', role: 'patient' },
  { id: 2, email: 'patient2@example.com', role: 'patient' },
  { id: 3, email: 'patient3@example.com', role: 'patient' },
  { id: 4, email: 'clinician1@example.com', role: 'clinician' },
]

const fail = (status: number, detail: string): ApiResult<never> => ({ ok: false, status, detail })

async function callApi<T>(path: string, body: unknown, token?: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) return fail(response.status, typeof data?.detail === 'string' ? data.detail : `Sign-in failed (${response.status})`)
    return { ok: true, data: data as T }
  } catch {
    return fail(0, 'Cannot reach the clinic server. Please try again.')
  }
}

/** mock and dev modes: sign in as one of the synthetic seed accounts. */
export async function demoLogin(email: string): Promise<ApiResult<Session>> {
  if (authMode === 'mock') {
    const user = DEMO_ACCOUNTS.find((a) => a.email === email)
    return user ? { ok: true, data: { token: 'mock', user } } : fail(401, 'Unknown demo account')
  }
  const result = await callApi<{ access_token: string; user: User }>('/auth/dev-login', { email })
  return result.ok ? { ok: true, data: { token: result.data.access_token, user: result.data.user } } : result
}

// --- Identity Platform (loaded only in that mode, so other builds don't ship Firebase) ---------

async function firebaseAuth() {
  const [{ initializeApp, getApps }, authSdk] = await Promise.all([import('firebase/app'), import('firebase/auth')])
  const app = getApps()[0] ?? initializeApp({
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  })
  return { auth: authSdk.getAuth(app), sdk: authSdk }
}

function firebaseMessage(error: unknown): string {
  const code = (error as { code?: string })?.code ?? ''
  if (code.includes('invalid-credential') || code.includes('wrong-password') || code.includes('user-not-found')) return 'Email or password is incorrect.'
  if (code.includes('email-already-in-use')) return 'An account with this email already exists. Sign in instead.'
  if (code.includes('weak-password')) return 'Please use a password of at least 6 characters.'
  if (code.includes('too-many-requests')) return 'Too many attempts. Please wait a moment and try again.'
  return 'Sign-in failed. Please try again.'
}

async function finishIdentityLogin(idToken: string): Promise<ApiResult<Session>> {
  // The backend verifies the token and creates the user on first sign-in
  const me = await callApi<User>('/me', undefined, idToken)
  return me.ok ? { ok: true, data: { token: idToken, user: me.data } } : me
}

export async function passwordLogin(email: string, password: string): Promise<ApiResult<Session>> {
  try {
    const { auth, sdk } = await firebaseAuth()
    const credential = await sdk.signInWithEmailAndPassword(auth, email, password)
    if (!credential.user.emailVerified) {
      await sdk.sendEmailVerification(credential.user)
      await sdk.signOut(auth)
      return fail(403, 'Please verify your email first. We just sent you a new link.')
    }
    return finishIdentityLogin(await credential.user.getIdToken())
  } catch (error) {
    return fail(401, firebaseMessage(error))
  }
}

export async function signUp(email: string, password: string): Promise<ApiResult<null>> {
  try {
    const { auth, sdk } = await firebaseAuth()
    const credential = await sdk.createUserWithEmailAndPassword(auth, email, password)
    await sdk.sendEmailVerification(credential.user)
    await sdk.signOut(auth)
    return { ok: true, data: null }
  } catch (error) {
    return fail(400, firebaseMessage(error))
  }
}

/** A fresh token for API calls. Identity Platform tokens expire hourly and are refreshed here. */
export async function currentToken(session: Session | null): Promise<string | null> {
  if (!session) return null
  if (authMode !== 'identity-platform') return session.token
  const { auth } = await firebaseAuth()
  return auth.currentUser ? auth.currentUser.getIdToken() : null
}

export async function signOutEverywhere() {
  if (authMode === 'identity-platform') {
    const { auth, sdk } = await firebaseAuth()
    await sdk.signOut(auth)
  }
}
