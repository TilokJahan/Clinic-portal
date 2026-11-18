import { useCallback, useEffect, useRef, useState } from 'react'
import { CalendarCheck, CalendarClock, Check, Loader2, TestTube2, Upload, X } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatDay, formatTime } from '../format'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import { EXAM_LABELS } from '../labTypes'
import type { LabRequestEntry, LabTimes } from '../types'

const WHO: Record<string, string> = { clinician: 'Clinician', physician: 'Physician', admin: 'Admin' }

/** The lab technician's work: tests clinical staff asked for, most urgent first. Mark one
 *  scheduled, upload its result (which completes it), or cancel it. */
export function LabRequestsPage({ readOnly = false }: { readOnly?: boolean }) {
  const [state, setState] = useState<'open' | 'done'>('open')
  const [rows, setRows] = useState<LabRequestEntry[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const r = await api.labRequests(state)
    if (r.ok) { setRows(r.data); setError('') } else setError(r.detail)
  }, [state])
  useEffect(() => {
    setRows(null)
    void load()
    const timer = setInterval(load, 15_000)
    return () => clearInterval(timer)
  }, [load])

  const count = (u: string) => rows?.filter((r) => r.urgency === u).length ?? 0
  return <>
    <div className="welcome-row"><div><div className="eyebrow">LAB</div><h1>Lab requests</h1>
      <p>{readOnly
        ? 'Every test the care team asked the lab for, most urgent first: proposed to the patient, booked, or done.'
        : 'Tests the care team asked for, most urgent first. Propose lab times to the patient, then upload the result to complete the request.'}</p></div></div>
    <div className="queue-toolbar">
      <div className="filter-tabs">
        <button className={state === 'open' ? 'active' : ''} onClick={() => setState('open')}>Open<span>{state === 'open' ? rows?.length ?? '' : ''}</span></button>
        <button className={state === 'done' ? 'active' : ''} onClick={() => setState('done')}>Done</button>
      </div>
      {state === 'open' && rows && <p className="field-hint">{count('urgent')} urgent · {count('soon')} soon · {count('routine')} routine</p>}
    </div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {rows === null && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading requests…</div>}
    {rows && rows.length === 0 && <div className="panel empty-state">{state === 'open' ? 'No open requests. Nice.' : 'Nothing completed yet.'}</div>}
    <div className="lab-request-grid">{rows?.map((r) => <RequestCard key={r.id} request={r} readOnly={readOnly} onChanged={load} />)}</div>
  </>
}

function RequestCard({ request, readOnly, onChanged }: { request: LabRequestEntry; readOnly: boolean; onChanged: () => void }) {
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
    if (r.ok) { setTimes(null); onChanged() } else setError(r.detail)
  }

  async function mark(status: 'scheduled' | 'cancelled') {
    setBusy(status); setError('')
    const r = await api.updateLabRequest(request.id, status)
    setBusy(null)
    if (r.ok) onChanged(); else setError(r.detail)
  }
  async function upload(file: File | undefined) {
    if (!file) return
    const problem = labFileError(file)
    if (problem) { setError(problem); return }
    setBusy('upload'); setError('')
    const r = await api.uploadLabReportAsTech(request.appointment_id, file, { examType: request.exam_type, requestId: request.id })
    setBusy(null)
    if (input.current) input.current.value = ''
    if (r.ok) onChanged(); else setError(r.detail)
  }

  return <article className={`panel lab-request-card ${request.urgency}`}>
    <div className="lab-request-head">
      <UrgencyPill urgency={request.urgency} />
      <span className={`request-state ${request.status}`}>{request.status}</span>
    </div>
    <h3><TestTube2 size={17} /> {EXAM_LABELS[request.exam_type]}</h3>
    <p><b>{request.patient_label}</b> · visit {formatDateTime(request.visit_starts_at)} with {request.provider_name}</p>
    {request.note && <p className="lab-request-note">“{request.note}”</p>}
    {request.status === 'scheduled' && request.scheduled_at && <p className="lab-visit-time"><CalendarCheck size={15} /> Lab visit <b>{formatDateTime(request.scheduled_at)}</b>, booked by the patient</p>}
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
    {request.status === 'completed' && <p className="saved-message"><Check size={14} /> Result uploaded</p>}
  </article>
}
