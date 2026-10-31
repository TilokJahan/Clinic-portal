/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) or "http" */
  readonly VITE_API_MODE?: string
  /** Base path of the appointment service. Defaults to /api (proxied). */
  readonly VITE_API_BASE?: string
  /** "dev" (default) or "identity-platform" */
  readonly VITE_AUTH_MODE?: string
  /** Public Identity Platform web config (not secrets) */
  readonly VITE_FIREBASE_API_KEY?: string
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string
}
