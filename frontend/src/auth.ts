import type { ApiResult, User } from './types'

// Sign-in. Three modes, all ending in a Session with a bearer token:
// - mock: no backend; pick a demo account, the token is a placeholder
// - dev: POST /api/auth/dev-login for a synthetic seed account (backend AUTH_MODE=dev)
// - entra: Microsoft Entra External ID (hosted sign-up/sign-in with email + password) via MSAL;
//   the ID token is refreshed by MSAL and verified by the backend (AUTH_MODE=entra-external-id)

export type AuthMode = 'mock' | 'dev' | 'entra'

export const authMode: AuthMode =
  import.meta.env.VITE_API_MODE !== 'http' ? 'mock'
    : import.meta.env.VITE_AUTH_MODE === 'entra' ? 'entra' : 'dev'

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

// --- Entra External ID (loaded only in that mode, so other builds don't ship MSAL) ------------

const SCOPES = ['openid', 'profile', 'email']
let msalApp: Promise<import('@azure/msal-browser').PublicClientApplication> | null = null

function msal() {
  msalApp ??= import('@azure/msal-browser').then(async ({ PublicClientApplication }) => {
    const app = new PublicClientApplication({
      auth: {
        clientId: import.meta.env.VITE_ENTRA_CLIENT_ID ?? '',
        authority: import.meta.env.VITE_ENTRA_AUTHORITY, // https://<tenant>.ciamlogin.com/
        redirectUri: window.location.origin,
      },
      cache: { cacheLocation: 'sessionStorage' },
    })
    await app.initialize()
    return app
  })
  return msalApp
}

function entraMessage(error: unknown): string {
  const code = (error as { errorCode?: string })?.errorCode ?? ''
  if (code === 'user_cancelled') return 'Sign-in was cancelled.'
  if (code === 'popup_window_error') return 'Please allow pop-ups for this site, then try again.'
  return 'Sign-in failed. Please try again.'
}

/** Opens Microsoft's sign-in page in a pop-up. With signUp, it opens on "create account". */
export async function entraLogin(signUp = false): Promise<ApiResult<Session>> {
  let idToken: string
  try {
    const app = await msal()
    const result = await app.loginPopup({ scopes: SCOPES, prompt: signUp ? 'create' : 'select_account' })
    app.setActiveAccount(result.account)
    idToken = result.idToken
  } catch (error) {
    return fail(401, entraMessage(error))
  }
  // The backend verifies the token and creates the user on first sign-in
  const me = await callApi<User>('/me', undefined, idToken)
  return me.ok ? { ok: true, data: { token: idToken, user: me.data } } : me
}

/** A fresh token for API calls. Entra ID tokens expire after about an hour; MSAL renews them. */
export async function currentToken(session: Session | null): Promise<string | null> {
  if (!session) return null
  if (authMode !== 'entra') return session.token
  try {
    const app = await msal()
    const account = app.getActiveAccount() ?? app.getAllAccounts()[0]
    if (!account) return null
    return (await app.acquireTokenSilent({ scopes: SCOPES, account })).idToken
  } catch {
    return null // the API then answers 401 and the app returns to the sign-in page
  }
}

export async function signOutEverywhere() {
  if (authMode === 'entra') await (await msal()).clearCache()
}
