/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) or "http" */
  readonly VITE_API_MODE?: string
  /** Base path of the appointment service. Defaults to /api (proxied). */
  readonly VITE_API_BASE?: string
}
