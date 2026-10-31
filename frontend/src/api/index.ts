import type { Api } from '../types'
import { httpApi } from './http'
import { mockApi } from './mock'

// The only place that decides mock vs real backend. Pages import `api` from here.
// VITE_API_MODE=mock (default for `npm run dev`) or http (`npm run dev:api`, Docker build).
export const apiMode: 'mock' | 'http' = import.meta.env.VITE_API_MODE === 'http' ? 'http' : 'mock'

export const api: Api = apiMode === 'http' ? httpApi : mockApi
