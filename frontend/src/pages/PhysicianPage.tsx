import { useCallback, useEffect, useState } from 'react'
import { Activity, Check, ClipboardCheck, Loader2, Stethoscope, X } from 'lucide-react'
import { api } from '../api'
import { AiLabel, ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatDay, formatTime } from '../format'
import { ClinicianLabSection, LabNeedsSection } from '../LabPanels'
import { EXAM_LABELS } from '../labTypes'
import type { QueueEntry } from '../types'

/** The physician's (doctor's) own schedule: upcoming visits with the symptoms, priority, tests
 *  and lab results, and the visits they completed recently. They request tests and complete a
 *  visit with a summary the patient reads. */
export function PhysicianPage() {
  const [entries, setEntries] = useState<QueueEntry[] | null>(null)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const load = useCallback(async () => {
    const r = await api.physicianSchedule()
    if (r.ok) { setEntries(r.data); setError('') } else setError(r.detail)
  }, [])
  useEffect(() => {
    void load()
    const timer = setInterval(load, 20_000) // new requests, labs and approvals show up on their own
    return () => clearInterval(timer)
  }, [load])

  const upcoming = entries?.filter((e) => e.status !== 'completed') ?? []
  const done = entries?.filter((e) => e.status === 'completed') ?? []
  const selected = entries?.find((e) => e.appointment_id === selectedId) ?? null
  const today = new Date().toDateString()

  return <>
    <div className="welcome-row"><div><div className="eyebrow">PHYSICIAN</div><h1>My schedule</h1>
      <p>Your visits with the symptoms, priority and test results. Request tests, then complete each visit with a summary for the patient.</p></div></div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {entries === null && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading your schedule…</div>}
    {entries && <>
      <div className="panel full-queue">
        <div className="table-head"><span>VISIT</span><span>REASON</span><span>TESTS</span><span>PRIORITY</span></div>
        {upcoming.map((e) => <ScheduleRow key={e.appointment_id} entry={e} today={new Date(e.starts_at).toDateString() === today} onSelect={() => setSelectedId(e.appointment_id)} />)}
        {upcoming.length === 0 && <div className="empty-state">No upcoming visits on your schedule.</div>}
      </div>
      {done.length > 0 && <>
        <h2 className="section-title">Completed in the last two weeks</h2>
        <div className="panel full-queue">
          {done.map((e) => <ScheduleRow key={e.appointment_id} entry={e} today={false} onSelect={() => setSelectedId(e.appointment_id)} />)}
        </div>
      </>}
    </>}
    {selected && <div className="detail-backdrop" onClick={() => setSelectedId(null)}><aside className="detail-drawer" onClick={(e) => e.stopPropagation()} aria-label="Visit details">
      <button className="drawer-close icon-button" onClick={() => setSelectedId(null)} aria-label="Close details"><X size={18} /></button>
      <div className="eyebrow">APPOINTMENT #{selected.appointment_id}</div>
      <h2>{selected.patient_label}</h2>
      <p className="drawer-subtitle">{selected.provider_name} · {formatDateTime(selected.starts_at)}{selected.awaiting_approval ? ' · awaiting approval' : ''}</p>
      {selected.triage
        ? <>
          <div className="ai-summary"><div className="ai-title"><AiLabel /></div><p>{selected.triage.summary}</p>
            {selected.triage.suggested_specialty && <span>Suggested specialty · <b>{selected.triage.suggested_specialty}</b></span>}</div>
          {selected.triage.red_flags.length > 0 && <div className="red-flag-box"><b><Activity size={15} /> Reported red flags</b>{selected.triage.red_flags.map((f) => <span key={f}>• {f}</span>)}</div>}
          <div className="drawer-section"><span className="drawer-label">PRIORITY</span><UrgencyPill urgency={selected.urgency} /></div>
        </>
        : <div className="drawer-section"><p>The patient hasn’t described their symptoms.</p></div>}
      <LabNeedsSection entry={selected} />
      <ClinicianLabSection appointmentId={selected.appointment_id} refreshKey={JSON.stringify(selected.lab)} />
      <CompleteVisit entry={selected} onDone={load} />
    </aside></div>}
  </>
}

function ScheduleRow({ entry, today, onSelect }: { entry: QueueEntry; today: boolean; onSelect: () => void }) {
  const gaps = entry.lab_needs?.filter((n) => n.status === 'missing' || n.status === 'outdated') ?? []
  const asked = entry.lab_requests?.filter((q) => q.status === 'requested' || q.status === 'scheduled') ?? []
  return <button className="queue-row queue-row-button" onClick={onSelect}>
    <div className="patient-cell"><div className="patient-avatar avatar-1"><Stethoscope size={16} /></div><div>
      <b>{formatDay(entry.starts_at)} · {formatTime(entry.starts_at)}{today && <> <span className="approval-badge">today</span></>}</b>
      <span>{entry.patient_label}{entry.awaiting_approval ? ' · awaiting approval' : ''}{entry.status === 'completed' ? ' · completed' : ''}</span></div></div>
    <div className="reason-cell"><span>{entry.triage?.summary ?? 'No symptoms sent'}</span></div>
    <div className="wait-cell">{gaps.length ? <small className="review-tag earlier">{gaps.map((n) => EXAM_LABELS[n.exam_type]).join(', ')} needed</small>
      : asked.length ? <small className="review-tag">{asked.length} requested</small> : '—'}</div>
    <div className="triage-cell"><UrgencyPill urgency={entry.urgency} /></div>
  </button>
}

function CompleteVisit({ entry, onDone }: { entry: QueueEntry; onDone: () => void }) {
  const [summary, setSummary] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setSummary(''); setError('') }, [entry.appointment_id])

  if (entry.status === 'completed') return <div className="drawer-section">
    <span className="drawer-label"><ClipboardCheck size={13} /> VISIT SUMMARY · SENT TO THE PATIENT</span>
    <p>{entry.visit_summary}</p>
  </div>

  async function complete() {
    setBusy(true); setError('')
    const r = await api.completeVisit(entry.appointment_id, summary.trim())
    setBusy(false)
    if (r.ok) onDone()
    else setError(r.detail)
  }

  return <div className="drawer-section review-actions">
    <span className="drawer-label"><ClipboardCheck size={13} /> COMPLETE THE VISIT</span>
    {entry.awaiting_approval
      ? <p className="field-hint">This booking is still waiting for a clinician’s approval.</p>
      : <>
        <textarea aria-label="Visit summary for the patient" rows={5} maxLength={3000} value={summary} onChange={(e) => setSummary(e.target.value)}
          placeholder="What you found, the advice or treatment, and the next steps. The patient reads this." />
        <button className="button button-primary" disabled={busy || !summary.trim()} onClick={complete}>
          {busy ? <Loader2 className="spin" size={14} /> : <Check size={14} />} Complete visit
        </button>
      </>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}
