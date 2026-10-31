import { useState } from 'react'
import { Activity, Check, Loader2, Search, ShieldCheck, X } from 'lucide-react'
import { api } from '../api'
import { AiLabel, ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatTime, formatWait, initials, waitMinutes } from '../format'
import type { QueueEntry, StreamStatus, Urgency } from '../types'
import { useQueue } from '../useQueue'

const FILTERS = ['all', 'urgent', 'soon', 'routine'] as const

export function LiveBadge({ status }: { status: StreamStatus }) {
  const text = { connecting: 'Connecting…', live: 'Live', reconnecting: 'Reconnecting…' }[status]
  return <span className={`live-badge ${status}`}><i />{text}</span>
}

export function QueueRow({ entry, compact = false, selected = false, onSelect }: { entry: QueueEntry; compact?: boolean; selected?: boolean; onSelect?: () => void }) {
  const t = entry.triage
  const cells = <>
    <div className="patient-cell"><div className={`patient-avatar avatar-${entry.appointment_id % 4}`}>{initials(entry.patient_label)}</div><div><b>{entry.patient_label}</b><span>{formatTime(entry.starts_at)} · {entry.provider_name}</span></div></div>
    <div className="reason-cell"><span>{t ? t.summary : 'Waiting for the patient’s intake'}</span>{t && t.red_flags.length > 0 && <small>{t.red_flags.length} red flag{t.red_flags.length > 1 ? 's' : ''}</small>}</div>
    <div className="wait-cell">{formatWait(waitMinutes(entry))}</div>
    <div className="triage-cell"><UrgencyPill urgency={t?.urgency ?? null} />{!compact && t?.reviewed_at && <small className={t.overridden ? 'review-tag overridden' : 'review-tag'}>{t.overridden ? 'overridden' : 'accepted'}</small>}</div>
  </>
  if (!onSelect) return <div className="queue-row">{cells}</div>
  return <button className={`queue-row queue-row-button ${selected ? 'selected' : ''}`} onClick={onSelect}>{cells}</button>
}

export function QueuePage() {
  const { queue, status, setQueue } = useQueue()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const [query, setQuery] = useState('')
  const [saving, setSaving] = useState<Urgency | null>(null)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const items = queue ?? []
  const selected = items.find((e) => e.appointment_id === selectedId) ?? null
  const q = query.toLowerCase()
  const visible = items.filter((e) =>
    (filter === 'all' || e.triage?.urgency === filter) &&
    `${e.patient_label} ${e.provider_name} ${e.triage?.summary ?? ''} ${e.triage?.red_flags.join(' ') ?? ''}`.toLowerCase().includes(q))

  async function review(urgency: Urgency) {
    if (!selected?.triage) return
    setSaving(urgency)
    setError('')
    const result = await api.review(selected.triage.id, urgency)
    setSaving(null)
    if (!result.ok) { setError(result.detail); return }
    // The stream will also send the new queue; update now so the drawer reacts instantly
    setQueue((old) => old?.map((e) => e.appointment_id === selected.appointment_id ? { ...e, triage: result.data } : e) ?? old)
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return <>
    <div className="welcome-row"><div><div className="eyebrow"><LiveBadge status={status} /></div><h1>Patient queue</h1><p>Review incoming patients and their AI-assisted intake summaries. Most urgent first.</p></div></div>
    <div className="queue-toolbar">
      <div className="search-box"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search patients, providers or symptoms" aria-label="Search queue" /></div>
      <div className="filter-tabs">{FILTERS.map((f) =>
        <button className={filter === f ? 'active' : ''} key={f} onClick={() => setFilter(f)}>{f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}<span>{f === 'all' ? items.length : items.filter((e) => e.triage?.urgency === f).length}</span></button>)}
      </div>
    </div>
    <div className="panel full-queue">
      <div className="table-head"><span>PATIENT</span><span>AI SUMMARY</span><span>WAITING</span><span>TRIAGE</span></div>
      {visible.map((e) => <QueueRow key={e.appointment_id} entry={e} selected={e.appointment_id === selectedId} onSelect={() => { setSelectedId(e.appointment_id); setSaved(false); setError('') }} />)}
      {queue === null && <div className="empty-state"><Loader2 className="spin" size={18} /> Loading queue…</div>}
      {queue !== null && visible.length === 0 && <div className="empty-state">{items.length ? 'No patients match that search.' : 'Nobody is waiting right now.'}</div>}
    </div>
    {selected && <div className="detail-backdrop" onClick={() => setSelectedId(null)}><aside className="detail-drawer" onClick={(e) => e.stopPropagation()} aria-label="Patient details">
      <button className="drawer-close icon-button" onClick={() => setSelectedId(null)} aria-label="Close details"><X size={18} /></button>
      <div className="eyebrow">APPOINTMENT #{selected.appointment_id}</div>
      <h2>{selected.patient_label}</h2>
      <p className="drawer-subtitle">{selected.provider_name} · {formatDateTime(selected.starts_at)} · waiting {formatWait(waitMinutes(selected))}</p>
      {!selected.triage
        ? <div className="drawer-section"><p>This patient hasn’t sent their symptoms yet. Their priority appears here once they do.</p></div>
        : <>
          <div className="ai-summary"><div className="ai-title"><AiLabel /></div><p>{selected.triage.summary}</p>
            {selected.triage.suggested_specialty && <span>Suggested specialty · <b>{selected.triage.suggested_specialty}</b></span>}
          </div>
          {selected.triage.red_flags.length > 0 && <div className="red-flag-box"><b><Activity size={15} /> Reported red flags</b>{selected.triage.red_flags.map((f) => <span key={f}>• {f}</span>)}</div>}
          <div className="drawer-section"><span className="drawer-label">AI SUGGESTION</span><UrgencyPill urgency={selected.triage.ai_urgency} /></div>
          <div className="review-actions"><span className="drawer-label">CLINICIAN DECISION</span>
            <p>{selected.triage.reviewed_at
              ? selected.triage.overridden ? `You overrode the AI (it suggested ${selected.triage.ai_urgency}).` : 'You accepted the AI suggestion.'
              : 'Accept the suggestion or set the final urgency.'}</p>
            <div>{(['urgent', 'soon', 'routine'] as Urgency[]).map((u) =>
              <button key={u} disabled={saving !== null} className={`review-choice ${selected.triage!.final_urgency === u ? 'chosen' : ''}`} onClick={() => review(u)}>
                {saving === u ? <Loader2 className="spin" size={13} /> : null}{u}{u === selected.triage!.ai_urgency ? ' (AI)' : ''}
              </button>)}</div>
            {saved && <span className="saved-message"><Check size={14} /> Decision saved</span>}
            {error && <ErrorBanner>{error}</ErrorBanner>}
          </div>
        </>}
      <div className="drawer-safety"><ShieldCheck size={16} /> AI suggestions support clinical judgment and are not a diagnosis.</div>
    </aside></div>}
  </>
}
