import { useCallback, useEffect, useRef, useState } from 'react'
import { CalendarCheck, Check, Loader2, TestTube2, Upload, X } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime } from '../format'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import { EXAM_LABELS } from '../labTypes'
import type { LabRequestEntry } from '../types'

const WHO: Record<string, string> = { clinician: 'Clinician', physician: 'Physician', admin: 'Admin' }

/** The lab technician's work: tests clinical staff asked for, most urgent first. Mark one
 *  scheduled, upload its result (which completes it), or cancel it. */
export function LabRequestsPage() {
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
      <p>Tests the care team asked for, most urgent first. Upload the result here to complete the request.</p></div></div>
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
    <div className="lab-request-grid">{rows?.map((r) => <RequestCard key={r.id} request={r} onChanged={load} />)}</div>
  </>
}

function RequestCard({ request, onChanged }: { request: LabRequestEntry; onChanged: () => void }) {
  const [busy, setBusy] = useState<'upload' | 'scheduled' | 'cancelled' | null>(null)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const open = request.status === 'requested' || request.status === 'scheduled'

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
    <p className="field-hint">Requested by {WHO[request.requested_by_role] ?? request.requested_by_role}, {formatDateTime(request.requested_at)}</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {open && <div className="request-actions">
      <label className={`button button-primary upload-button ${busy ? 'disabled' : ''}`}>
        {busy === 'upload' ? <Loader2 className="spin" size={16} /> : <Upload size={16} />} Upload result
        <input ref={input} type="file" accept={LAB_FILE_ACCEPT} hidden disabled={busy !== null} onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      {request.status === 'requested' && <button type="button" className="button button-secondary" disabled={busy !== null} onClick={() => mark('scheduled')}>
        {busy === 'scheduled' ? <Loader2 className="spin" size={16} /> : <CalendarCheck size={16} />} Mark scheduled</button>}
      <button type="button" className="text-button" disabled={busy !== null} onClick={() => mark('cancelled')}><X size={14} /> Cancel</button>
    </div>}
    {request.status === 'completed' && <p className="saved-message"><Check size={14} /> Result uploaded</p>}
  </article>
}
