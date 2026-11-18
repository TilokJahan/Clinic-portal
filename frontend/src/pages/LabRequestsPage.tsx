import { useCallback, useEffect, useRef, useState } from 'react'
import { CalendarCheck, CalendarClock, Check, Loader2, TestTube2, Upload, X } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatDay, formatTime } from '../format'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import { EXAM_LABELS } from '../labTypes'
import type { LabRequestEntry, LabTimes } from '../types'

const WHO: Record<string, string> = { clinician: 'Clinician', physician: 'Physician', admin: 'Admin' }

type Tab = 'todo' | 'booked' | 'past'
const TABS: { id: Tab; label: string; empty: string }[] = [
  { id: 'todo', label: 'To do', empty: 'Nothing to do. Nice.' },
  { id: 'booked', label: 'Booked', empty: 'No lab visits booked yet.' },
  { id: 'past', label: 'Past', empty: 'Nothing completed or cancelled yet.' },
]
const tabOf = (r: LabRequestEntry): Tab =>
  r.status === 'requested' || r.status === 'proposed' ? 'todo' : r.status === 'scheduled' ? 'booked' : 'past'

/** The lab technician's work, in three lists: to do (propose times), booked (the patient chose a
 *  time; upload the result), and past (completed or cancelled). A request moves between them and
 *  never just disappears. */
export function LabRequestsPage({ readOnly = false }: { readOnly?: boolean }) {
  const [tab, setTab] = useState<Tab>('todo')
  const [rows, setRows] = useState<LabRequestEntry[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [open, done] = await Promise.all([api.labRequests('open'), api.labRequests('done')])
    if (open.ok && done.ok) { setRows([...open.data, ...done.data]); setError('') } else setError(!open.ok ? open.detail : !done.ok ? done.detail : '')
  }, [])
  useEffect(() => {
    void load()
    const timer = setInterval(load, 15_000)
    return () => clearInterval(timer)
  }, [load])

  const changed = (message: string) => { setNotice(message); void load() }
  const lists: Record<Tab, LabRequestEntry[]> = { todo: [], booked: [], past: [] }
  for (const r of rows ?? []) lists[tabOf(r)].push(r)
  // Booked: by the time of the lab visit
  lists.booked.sort((x, y) => (x.scheduled_at ?? '').localeCompare(y.scheduled_at ?? ''))
  const shown = lists[tab]
  const count = (u: string) => lists.todo.filter((r) => r.urgency === u).length
  return <>
    <div className="welcome-row"><div><div className="eyebrow">LAB</div><h1>Lab requests</h1>
      <p>{readOnly
        ? 'Every test the care team asked the lab for: still to arrange, booked by the patient, or past.'
        : 'Tests the care team asked for, most urgent first. Propose lab times to the patient; once they book, upload the result to complete the request.'}</p></div></div>
    <div className="queue-toolbar">
      <div className="filter-tabs lab-tabs" role="tablist" aria-label="Lab requests">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'active' : ''}
          onClick={() => { setTab(t.id); setNotice('') }}>{t.label}<span>{rows ? lists[t.id].length : ''}</span></button>)}
      </div>
      {tab === 'todo' && rows && <p className="field-hint">{count('urgent')} urgent · {count('soon')} soon · {count('routine')} routine</p>}
    </div>
    {notice && <p className="lab-upload-success" role="status">{notice}</p>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {rows === null && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading requests…</div>}
    {rows && shown.length === 0 && <div className="panel empty-state">{TABS.find((t) => t.id === tab)!.empty}</div>}
    <div className="lab-request-grid">{shown.map((r) => <RequestCard key={r.id} request={r} readOnly={readOnly} onChanged={changed} />)}</div>
  </>
}

function RequestCard({ request, readOnly, onChanged }: { request: LabRequestEntry; readOnly: boolean; onChanged: (message: string) => void }) {
  const [busy, setBusy] = useState<'upload' | 'scheduled' | 'cancelled' | 'propose' | null>(null)
  const [error, setError] = useState('')
  const [times, setTimes] = useState<LabTimes | null>(null)
  const [chosen, setChosen] = useState<string[]>([])
  const input = useRef<HTMLInputElement>(null)
  const open = request.status === 'requested' || request.status === 'proposed' || request.status === 'scheduled'

  async function findTimes() {
    setError('')
    const r = await api.labTimes(request.id)
    if (r.ok) { setTimes(r.data); setChosen(r.data.times.slice(0, 3)) } else setError(r.detail)
  }
  async function propose() {
    setBusy('propose'); setError('')
    const r = await api.proposeLabTimes(request.id, chosen)
    setBusy(null)
    if (r.ok) { setTimes(null); onChanged('Times sent to the patient. When they book one, the request moves to Booked.') } else setError(r.detail)
  }

  async function mark(status: 'scheduled' | 'cancelled') {
    setBusy(status); setError('')
    const r = await api.updateLabRequest(request.id, status)
    setBusy(null)
    if (r.ok) onChanged(status === 'cancelled' ? 'Request cancelled. You can find it under Past.' : 'Marked as booked.'); else setError(r.detail)
  }
  async function upload(file: File | undefined) {
    if (!file) return
    const problem = labFileError(file)
    if (problem) { setError(problem); return }
    setBusy('upload'); setError('')
    const r = await api.uploadLabReportAsTech(request.appointment_id, file, { examType: request.exam_type, requestId: request.id })
    setBusy(null)
    if (input.current) input.current.value = ''
    if (r.ok) onChanged('Result uploaded and the request completed. You can find it under Past.'); else setError(r.detail)
  }

  return <article className={`panel lab-request-card ${request.urgency}`}>
    <div className="lab-request-head">
      <UrgencyPill urgency={request.urgency} />
      <span className={`request-state ${request.status}`}>{request.status}</span>
    </div>
    <h3><TestTube2 size={17} /> {EXAM_LABELS[request.exam_type]}</h3>
    <p><b>{request.patient_label}</b> · visit {formatDateTime(request.visit_starts_at)} with {request.provider_name}</p>
    {request.note && <p className="lab-request-note">“{request.note}”</p>}
    {request.scheduled_at && (request.status === 'scheduled' || !open) && <p className="lab-visit-time"><CalendarCheck size={15} /> Lab visit <b>{formatDateTime(request.scheduled_at)}</b>{request.status === 'scheduled' ? ', booked by the patient' : ''}</p>}
    {request.status === 'proposed' && <p className="field-hint">Proposed to the patient: {(request.proposed_times ?? []).map((t) => formatDateTime(t)).join(' · ')}. Waiting for their answer.</p>}
    <p className="field-hint">Requested by {WHO[request.requested_by_role] ?? request.requested_by_role}, {formatDateTime(request.requested_at)}</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {!readOnly && open && request.status !== 'scheduled' && <div className="lab-propose">
      {times === null
        ? <button type="button" className="button button-primary" onClick={findTimes}><CalendarClock size={16} /> {request.status === 'proposed' ? 'Propose other times' : 'Propose lab times'}</button>
        : <>
          <span className="drawer-label">{times.in_time ? `FREE LAB TIMES WITHIN ${times.within_hours <= 24 ? '24 HOURS' : times.within_hours <= 72 ? '3 DAYS' : '2 WEEKS'}` : 'NOTHING FREE IN TIME · FIRST FREE TIMES'}</span>
          <div className="time-chips">{times.times.map((t) => {
            const on = chosen.includes(t)
            return <button type="button" key={t} aria-pressed={on} disabled={!on && chosen.length >= 3} className={`review-choice ${on ? 'chosen' : ''}`}
              onClick={() => setChosen(on ? chosen.filter((x) => x !== t) : [...chosen, t])}>{formatDay(t)} · {formatTime(t)}</button>
          })}</div>
          <div className="request-actions">
            <button type="button" className="button button-primary" disabled={!chosen.length || busy !== null} onClick={propose}>
              {busy === 'propose' ? <Loader2 className="spin" size={16} /> : null}Send {chosen.length} time{chosen.length === 1 ? '' : 's'} to the patient</button>
            <button type="button" className="text-button" onClick={() => setTimes(null)}>Cancel</button>
          </div>
        </>}
    </div>}
    {!readOnly && open && <div className="request-actions">
      <label className={`button button-primary upload-button ${busy ? 'disabled' : ''}`}>
        {busy === 'upload' ? <Loader2 className="spin" size={16} /> : <Upload size={16} />} Upload result
        <input ref={input} type="file" accept={LAB_FILE_ACCEPT} hidden disabled={busy !== null} onChange={(e) => upload(e.target.files?.[0])} />
      </label>

      <button type="button" className="text-button" disabled={busy !== null} onClick={() => mark('cancelled')}><X size={14} /> Cancel</button>
    </div>}
    {request.status === 'completed' && <p className="saved-message"><Check size={14} /> Result uploaded{request.updated_at ? `, ${formatDateTime(request.updated_at)}` : ''}</p>}
    {request.status === 'cancelled' && <p className="field-hint"><X size={13} /> Cancelled{request.updated_at ? `, ${formatDateTime(request.updated_at)}` : ''}</p>}
  </article>
}
