/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) or "http" */
  readonly VITE_API_MODE?: string
  /** Base path of the appointment service. Defaults to /api (proxied). */
  readonly VITE_API_BASE?: string
  /** "dev" (default) or "entra" */
  readonly VITE_AUTH_MODE?: string
  /** Entra External ID app registration (public values, not secrets) */
  readonly VITE_ENTRA_CLIENT_ID?: string
  /** https://<tenant subdomain>.ciamlogin.com/ */
  readonly VITE_ENTRA_AUTHORITY?: string
}
