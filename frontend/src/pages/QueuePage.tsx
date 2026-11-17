import { useEffect, useState } from 'react'
import { Activity, Check, Loader2, Search, ShieldCheck, X } from 'lucide-react'
import { api } from '../api'
import { AiLabel, ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatTime, formatWait, initials, waitMinutes } from '../format'
import { loadPatientMessages, messagesForPatientLabel, PATIENT_MESSAGES_STORAGE_KEY, type PatientMessage } from '../patientMessages'
import type { QueueEntry, StreamStatus, Urgency } from '../types'
import { useQueue } from '../useQueue'
import { ClinicianLabSection, LabReasonChip } from '../LabPanels'
import { ClinicianOfferSection } from '../Scheduling'

const FILTERS = ['all', 'requests', 'urgent', 'soon', 'routine'] as const
const FILTER_LABEL: Record<(typeof FILTERS)[number], string> = { all: 'All', requests: 'Awaiting approval', urgent: 'Urgent', soon: 'Soon', routine: 'Routine' }

export function LiveBadge({ status }: { status: StreamStatus }) {
  const text = { connecting: 'Connecting…', live: 'Live', reconnecting: 'Reconnecting…' }[status]
  return <span className={`live-badge ${status}`}><i />{text}</span>
}

export function QueueRow({ entry, compact = false, selected = false, onSelect }: { entry: QueueEntry; compact?: boolean; selected?: boolean; onSelect?: () => void }) {
  const t = entry.triage
  const cells = <>
    <div className="patient-cell"><div className={`patient-avatar avatar-${entry.appointment_id % 4}`}>{initials(entry.patient_label)}</div><div><b>{entry.patient_label}</b>{entry.awaiting_approval && <> <span className="approval-badge">awaiting approval</span></>}<span>{formatTime(entry.starts_at)} · {entry.provider_name}</span></div></div>
    <div className="reason-cell"><span>{t ? t.summary : entry.lab ? 'Lab report received' : 'Waiting for the patient’s intake'}</span>{t && t.red_flags.length > 0 && <small>{t.red_flags.length} red flag{t.red_flags.length > 1 ? 's' : ''}</small>}<LabReasonChip reason={entry.lab?.reason ?? null} urgency={entry.lab?.urgency ?? null} /></div>
    <div className="wait-cell">{formatWait(waitMinutes(entry))}</div>
    <div className="triage-cell"><UrgencyPill urgency={entry.urgency} />{!compact && entry.needs_earlier_visit && <small className="review-tag earlier">needs earlier visit</small>}{!compact && entry.offer_pending && <small className="review-tag">offer sent</small>}{!compact && t?.reviewed_at && <small className={t.overridden ? 'review-tag overridden' : 'review-tag'}>{t.overridden ? 'overridden' : 'accepted'}</small>}</div>
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
  const [patientMessages, setPatientMessages] = useState<PatientMessage[]>([])
  const [patientMessagesError, setPatientMessagesError] = useState('')

  useEffect(() => {
    function refreshPatientMessages() {
      try {
        setPatientMessages(loadPatientMessages())
        setPatientMessagesError('')
      } catch (reason) {
        setPatientMessagesError(reason instanceof Error ? reason.message : 'Patient messages could not be loaded.')
      }
    }

    refreshPatientMessages()
    const handleStorage = (event: StorageEvent) => {
      if (event.key === PATIENT_MESSAGES_STORAGE_KEY || event.key === null) refreshPatientMessages()
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  const items = queue ?? []
  const selected = items.find((e) => e.appointment_id === selectedId) ?? null
  const selectedMessages = selected ? messagesForPatientLabel(patientMessages, selected.patient_label) : []
  const q = query.toLowerCase()
  const matches = (e: QueueEntry, f: (typeof FILTERS)[number]) =>
    f === 'all' || (f === 'requests' ? Boolean(e.awaiting_approval) : e.urgency === f)
  const visible = items.filter((e) =>
    matches(e, filter) &&
    `${e.patient_label} ${e.provider_name} ${e.triage?.summary ?? ''} ${e.triage?.red_flags.join(' ') ?? ''} ${e.lab?.reason ?? ''}`.toLowerCase().includes(q))

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
        <button className={filter === f ? 'active' : ''} key={f} onClick={() => setFilter(f)}>{FILTER_LABEL[f]}<span>{items.filter((e) => matches(e, f)).length}</span></button>)}
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
        ? <div className="drawer-section"><p>This patient hasn’t sent their symptoms yet.{selected.lab ? ' Their lab report is below.' : ' Their priority appears here once they do.'}</p></div>
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
      <ApprovalSection entry={selected} />
      <ClinicianOfferSection entry={selected} />
      <ClinicianLabSection appointmentId={selected.appointment_id} refreshKey={JSON.stringify(selected.lab)} />
      <div className="drawer-section queue-patient-messages">
        <span className="drawer-label">DEMO MESSAGES — THIS BROWSER</span>
        <p className="field-hint">Sample messages saved in this browser only. Messages are not delivered between browsers or devices.</p>
        {patientMessagesError
          ? <ErrorBanner>{patientMessagesError}</ErrorBanner>
          : selectedMessages.length
            ? <div className="queue-patient-message-list">{selectedMessages.map((item) => (
                <article className="panel queue-patient-message" key={item.id}>
                  <p>{item.message}</p>
                  <time dateTime={item.sentAt}>{new Date(item.sentAt).toLocaleString()}</time>
                </article>
              ))}</div>
            : <p>No demo messages saved for this patient in this browser.</p>}
      </div>
      <div className="drawer-safety"><ShieldCheck size={16} /> AI suggestions support clinical judgment and are not a diagnosis. Critical lab values come from fixed rules, not the AI.</div>
    </aside></div>}
  </>
}

/** A booking request: approve it, or decline it with a note the patient sees. Offering a
 *  different time is the section below; the patient accepting it counts as approved. */
function ApprovalSection({ entry }: { entry: QueueEntry }) {
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { setDeclining(false); setReason(''); setError('') }, [entry.appointment_id])
  if (!entry.awaiting_approval) return null

  async function act(kind: 'approve' | 'decline') {
    setBusy(kind)
    setError('')
    const r = kind === 'approve' ? await api.approve(entry.appointment_id) : await api.decline(entry.appointment_id, reason)
    setBusy(null)
    // On success the live queue sends the change; the drawer updates or the request leaves it
    if (!r.ok) setError(r.detail)
  }

  const limit = entry.urgency === 'urgent' ? 'within 24 hours' : entry.urgency === 'soon' ? 'within 3 days' : null
  return <div className="drawer-section approval-section">
    <span className="drawer-label">BOOKING REQUEST</span>
    <p>Requested for <b>{formatDateTime(entry.starts_at)}</b> with {entry.provider_name}. The time is held until you decide.</p>
    {!entry.triage
      ? <p className="field-hint">Waiting for the patient’s symptoms. You can approve once they arrive.</p>
      : entry.needs_earlier_visit
        ? <p className="field-hint">The priority is <b>{entry.urgency}</b>, so they should be seen {limit}. This time is later than that: offer an earlier time below, or approve it if this time is right.</p>
        : <p className="field-hint">Priority <b>{entry.urgency}</b>{limit ? ` (to be seen ${limit})` : ''}. The requested time fits.</p>}
    <div className="request-actions">
      <button type="button" className="button button-primary" disabled={!entry.triage || busy !== null} onClick={() => act('approve')}>
        {busy === 'approve' ? <Loader2 className="spin" size={16} /> : <Check size={16} />}Approve
      </button>
      {!declining
        ? <button type="button" className="button button-secondary" disabled={busy !== null} onClick={() => setDeclining(true)}>Decline…</button>
        : <>
          <textarea aria-label="Note to the patient" value={reason} maxLength={500} rows={2} onChange={(e) => setReason(e.target.value)}
            placeholder="Optional note the patient will see, e.g. please book with a specialist." />
          <button type="button" className="button button-secondary" disabled={busy !== null} onClick={() => act('decline')}>
            {busy === 'decline' ? <Loader2 className="spin" size={16} /> : null}Decline request
          </button>
          <button type="button" className="text-button" disabled={busy !== null} onClick={() => setDeclining(false)}>Cancel</button>
        </>}
    </div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}
