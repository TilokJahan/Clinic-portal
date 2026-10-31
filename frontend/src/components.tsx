import type { ReactNode } from 'react'
import { AlertCircle, Sparkles } from 'lucide-react'
import type { Urgency } from './types'

export function UrgencyPill({ urgency }: { urgency: Urgency | null }) {
  if (!urgency) return <span className="urgency-pill pending"><i />awaiting intake</span>
  return <span className={`urgency-pill ${urgency}`}><i />{urgency}</span>
}

/** Required on every AI result (issue #12): the AI suggests, a clinician decides. */
export function AiLabel() {
  return <span className="ai-label"><Sparkles size={13} /> AI suggestion · clinician decides</span>
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return <div className="error-banner" role="alert"><AlertCircle size={16} /><span>{children}</span></div>
}

export function Stat({ icon, label, value, note, tone }: { icon: ReactNode; label: string; value: string; note: string; tone: string }) {
  return <div className="stat-card"><div className={`stat-icon ${tone}`}>{icon}</div><span className="stat-label">{label}</span><b className="stat-value">{value}</b><span className="stat-note">{note}</span></div>
}
