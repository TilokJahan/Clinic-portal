import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, FlaskConical, Loader2, ShieldCheck, TestTube2, Upload } from 'lucide-react'
import { api } from './api'
import { AiLabel, ErrorBanner, UrgencyPill } from './components'
import { formatDateTime, todayInput } from './format'
import { daysAgo, EXAM_LABELS, EXAM_TYPES, NEED_LABEL, RECENT_DAYS } from './labTypes'
import type { ExamType, LabFlag, LabNeed, LabReport, LabResult, QueueEntry, Urgency } from './types'
import { LAB_FILE_ACCEPT, labFileError } from './labUpload'

const range = (r: LabResult) =>
  r.ref_low != null && r.ref_high != null ? `${r.ref_low}–${r.ref_high}`
    : r.ref_high != null ? `< ${r.ref_high}` : r.ref_low != null ? `> ${r.ref_low}` : '—'

const value = (r: LabResult) => (r.value == null ? '?' : `${r.value}${r.unit ? ` ${r.unit}` : ''}`)

// Clinicians see the rule flag; patients see plain words (no "critical" wording)
const STAFF_FLAG: Record<LabFlag, string> = {
  normal: 'normal', low: 'low', high: 'high', critical_low: 'critical low', critical_high: 'critical high', unknown: 'unreadable',
}
const PATIENT_FLAG: Record<LabFlag, string> = {
  normal: 'Within range', low: 'Below range', high: 'Above range', critical_low: 'Below range', critical_high: 'Above range', unknown: '—',
}

export function LabFlagPill({ flag, patient = false }: { flag: LabFlag; patient?: boolean }) {
  // Patients get calm amber for anything out of range; the red "critical" styling is for staff
  const style = patient && flag.startsWith('critical') ? flag.replace('critical_', '') : flag
  return <span className={`lab-flag ${style}`}>{patient ? PATIENT_FLAG[flag] : STAFF_FLAG[flag]}</span>
}

/** The reason chip on queue rows, e.g. "Critical: potassium 6.8 mmol/L". */
export function LabReasonChip({ reason, urgency }: { reason: string | null; urgency: string | null }) {
  if (!reason) return null
  return <small className={`lab-reason ${urgency ?? ''}`}><FlaskConical size={11} /> {reason}</small>
}

function useLabReports(appointmentId: number, refreshKey: unknown) {
  const [reports, setReports] = useState<LabReport[] | null>(null)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const load = useCallback(async () => {
    const current = ++requestId.current
    const result = await api.labReports(appointmentId)
    if (current !== requestId.current) return
    setError(result.ok ? '' : result.detail)
    setReports(result.ok ? result.data : [])
  }, [appointmentId])
  useEffect(() => {
    setReports(null)
    setError('')
    void load()
    return () => { requestId.current++ }
  }, [load, refreshKey])
  return { reports, load, error }
}

/** Patient: upload a lab report for an appointment and see it once a clinician has approved it. */
export function PatientLabCard({ appointmentId }: { appointmentId: number }) {
  const { reports, load, error: reportError } = useLabReports(appointmentId, null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [examType, setExamType] = useState<ExamType>('blood')
  const [takenOn, setTakenOn] = useState('')
  const input = useRef<HTMLInputElement>(null)

  // While a report is being read, check again every few seconds
  useEffect(() => {
    if (!reports?.some((r) => r.status === 'processing')) return
    const timer = setTimeout(load, 3000)
    return () => clearTimeout(timer)
  }, [reports, load])

  async function upload(file: File | undefined) {
    if (!file) return
    setError('')
    const problem = labFileError(file)
    if (problem) { setError(problem); return }
    setBusy(true)
    const result = await api.uploadLabReport(appointmentId, file, { examType, takenOn: takenOn || undefined })
    setBusy(false)
    if (input.current) input.current.value = ''
    if (!result.ok) { setError(result.detail); return }
    await load()
  }

  return <div className="panel lab-card">
    <div className="lab-card-head"><div className="info-icon mint"><FlaskConical /></div><div><h3>Tests and results</h3>
      <p>Have a recent result (blood test, ultrasound, X-ray, MRI…)? Attach it (PDF or photo) and your care team will review it with your visit.</p></div></div>
    {reports?.map((r) => <PatientReport key={r.id} report={r} />)}
    {reports === null && <div className="lab-status"><Loader2 className="spin" size={14} />Loading lab reports…</div>}
    {reportError && <><ErrorBanner>{reportError}</ErrorBanner><button type="button" className="text-button left" onClick={() => void load()}>Retry loading reports</button></>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <ExamFields examType={examType} onExamType={setExamType} takenOn={takenOn} onTakenOn={setTakenOn} />
    <label className={`button button-secondary upload-button ${busy ? 'disabled' : ''}`}>
      {busy ? <Loader2 className="spin" size={16} /> : <Upload size={16} />} {busy ? 'Uploading…' : 'Attach a lab report'}
      <input ref={input} type="file" accept={LAB_FILE_ACCEPT} hidden disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
    </label>
    <span className="field-hint">Only upload your own synthetic test reports. Max 10 MB.</span>
  </div>
}

function PatientReport({ report }: { report: LabReport }) {
  if (!report.explanation_approved) {
    const text = report.status === 'processing' ? 'Reading your report…'
      : report.status === 'failed' ? 'We could not read this report. Your care team will look at it.'
      : 'Received. Your care team is reviewing it.'
    return <div className="lab-status"><FileText size={15} /> <span>{EXAM_LABELS[report.exam_type ?? 'blood']} from {formatDateTime(report.uploaded_at)}: {text}</span></div>
  }
  return <div className="lab-approved">
    <div className="lab-status"><ShieldCheck size={15} /> <span>Reviewed by your care team</span></div>
    <p>{report.patient_explanation}</p>
    {report.results.length > 0 && <table className="lab-table"><thead><tr><th>Test</th><th>Your result</th><th>Usual range</th><th></th></tr></thead>
      <tbody>{report.results.map((r, i) => <tr key={i}><td>{r.display_name}</td><td>{value(r)}</td><td>{range(r)}</td><td><LabFlagPill flag={r.flag} patient /></td></tr>)}</tbody>
    </table>}
  </div>
}

/** Clinician (queue drawer): flagged results, summary, original file, approve the explanation. */
export function ClinicianLabSection({ appointmentId, refreshKey }: { appointmentId: number; refreshKey: unknown }) {
  const { reports, load, error } = useLabReports(appointmentId, refreshKey)
  if (error) return <div className="drawer-section"><ErrorBanner>{error}</ErrorBanner><button type="button" className="text-button left" onClick={() => void load()}>Retry loading reports</button></div>
  if (reports === null) return <div className="drawer-section"><Loader2 className="spin" size={14} /> Loading lab reports…</div>
  if (reports.length === 0) return null
  return <>{reports.map((r) => <ClinicianReport key={r.id} report={r} />)}</>
}

function ClinicianReport({ report }: { report: LabReport }) {
  const [text, setText] = useState(report.patient_explanation ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(report.explanation_approved)
  const [error, setError] = useState('')
  useEffect(() => { setText(report.patient_explanation ?? ''); setSaved(report.explanation_approved) }, [report])

  async function openOriginal() {
    const result = await api.labReportFile(report.id)
    if (!result.ok) { setError(result.detail); return }
    window.open(URL.createObjectURL(result.data), '_blank', 'noopener')
  }

  async function approve() {
    setSaving(true); setError('')
    const result = await api.approveLabExplanation(report.id, text.trim())
    setSaving(false)
    if (result.ok) setSaved(true)
    else setError(result.detail)
  }

  const verify = report.results.filter((r) => r.needs_verification)
  return <div className="drawer-section lab-section">
    <div className="lab-section-head"><span className="drawer-label"><FlaskConical size={13} /> {EXAM_LABELS[report.exam_type ?? 'blood'].toUpperCase()} · {report.taken_on ? `TAKEN ${report.taken_on}` : formatDateTime(report.uploaded_at)}</span>
      {report.lab_urgency && <UrgencyPill urgency={report.lab_urgency} />}</div>
    {report.status === 'processing' && <p><Loader2 className="spin" size={14} /> Reading the report…</p>}
    {report.status === 'failed' && <ErrorBanner>The report couldn't be read. Open the original and review it by hand.</ErrorBanner>}
    {report.reason && <p className={`lab-reason-line ${report.lab_urgency}`}>{report.reason}</p>}
    {report.results.length > 0 && <table className="lab-table"><thead><tr><th>Test</th><th>Value</th><th>Range</th><th>Flag</th></tr></thead>
      <tbody>{report.results.map((r, i) => <tr key={i} className={r.flag.startsWith('critical') ? 'critical-row' : ''}>
        <td>{r.display_name}{r.needs_verification && <span className="verify-tag" title={r.verification_reason ?? ''}><AlertTriangle size={11} /> verify</span>}</td>
        <td>{value(r)}</td><td>{range(r)}</td><td><LabFlagPill flag={r.flag} /></td></tr>)}</tbody>
    </table>}
    {verify.length > 0 && <p className="field-hint">{verify.length} value(s) need checking against the original: {verify.map((r) => `${r.display_name} (${r.verification_reason})`).join('; ')}.</p>}
    {report.clinician_summary && <div className="ai-summary"><div className="ai-title"><AiLabel /></div><p>{report.clinician_summary}</p></div>}
    <button className="text-button left" onClick={openOriginal}><FileText size={13} /> Open the original report</button>
    {report.status !== 'processing' && report.status !== 'failed' && <div className="review-actions">
      <span className="drawer-label">EXPLANATION FOR THE PATIENT {saved ? '· APPROVED' : '· DRAFT, NOT SENT'}</span>
      <textarea value={text} rows={5} maxLength={3000} onChange={(e) => { setText(e.target.value); setSaved(false) }} aria-label="Patient explanation" />
      <button className="button button-primary" disabled={saving || !text.trim() || saved} onClick={approve}>
        {saving ? <Loader2 className="spin" size={14} /> : <Check size={14} />} {saved ? 'Approved' : 'Approve for patient'}
      </button>
      <span className="field-hint">The patient sees the results and this text only after you approve.</span>
    </div>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}

/** The kind of test and when it was taken, before uploading a result. */
export function ExamFields({ examType, onExamType, takenOn, onTakenOn }: { examType: ExamType; onExamType: (e: ExamType) => void; takenOn?: string; onTakenOn?: (d: string) => void }) {
  const age = takenOn ? daysAgo(takenOn) : null
  return <div className="exam-fields">
    <label>Kind of test
      <select value={examType} onChange={(e) => onExamType(e.target.value as ExamType)}>
        {EXAM_TYPES.map((t) => <option key={t} value={t}>{EXAM_LABELS[t]}</option>)}
      </select>
    </label>
    {onTakenOn && <label>Date of the test
      <input type="date" value={takenOn} max={todayInput()} onChange={(e) => onTakenOn(e.target.value)} />
    </label>}
    {age !== null && age > RECENT_DAYS && <p className="field-hint warn">This result is more than {RECENT_DAYS} days old. Your care team may ask for a new test.</p>}
  </div>
}

const NEED_TONE: Record<LabNeed['status'], string> = { recent: 'ok', requested: 'info', outdated: 'warn', missing: 'warn' }

/** Clinician and physician drawer: the tests the symptoms suggest, what is on file, the lab
 *  requests, and a form to ask the lab for a test with an urgency. */
export function LabNeedsSection({ entry }: { entry: QueueEntry }) {
  const needs = entry.lab_needs ?? []
  const requests = entry.lab_requests ?? []
  const firstGap = needs.find((n) => n.status === 'missing' || n.status === 'outdated')?.exam_type
  const [open, setOpen] = useState(false)
  const [examType, setExamType] = useState<ExamType>(firstGap ?? 'blood')
  const [urgency, setUrgency] = useState<Urgency>(entry.urgency ?? 'routine')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState('')
  useEffect(() => { setOpen(false); setNote(''); setError(''); setSent('') }, [entry.appointment_id])
  useEffect(() => { setExamType(firstGap ?? 'blood'); setUrgency(entry.urgency ?? 'routine') }, [entry.appointment_id, firstGap, entry.urgency])
  if (entry.status !== 'booked' && entry.status !== 'checked_in' && !needs.length && !requests.length) return null

  async function send() {
    setBusy(true); setError('')
    const r = await api.requestLab(entry.appointment_id, examType, urgency, note)
    setBusy(false)
    if (r.ok) { setSent(`${EXAM_LABELS[examType]} requested (${urgency}).`); setOpen(false); setNote('') } else setError(r.detail)
  }

  const gaps = needs.filter((n) => n.status === 'missing' || n.status === 'outdated')
  return <div className="drawer-section lab-needs">
    <span className="drawer-label"><TestTube2 size={13} /> TESTS</span>
    {needs.length > 0
      ? <ul className="need-list">{needs.map((n) => <li key={n.exam_type} className={`need ${NEED_TONE[n.status]}`}>
          <b>{EXAM_LABELS[n.exam_type]}</b><span>{NEED_LABEL[n.status]}</span></li>)}</ul>
      : <p className="field-hint">The symptoms don’t suggest a particular test.</p>}
    {gaps.length > 0 && <p className="need-alert"><AlertTriangle size={14} /> {gaps.map((n) => EXAM_LABELS[n.exam_type]).join(', ')} {gaps.length > 1 ? 'are' : 'is'} suggested but {gaps.every((n) => n.status === 'missing') ? 'not uploaded' : 'missing or out of date'}. Consider requesting {gaps.length > 1 ? 'them' : 'it'} from the lab.</p>}
    {requests.length > 0 && <ul className="request-list">{requests.map((q) => <li key={q.id}>
      <UrgencyPill urgency={q.urgency} /> <b>{EXAM_LABELS[q.exam_type]}</b> <span className={`request-state ${q.status}`}>{q.status}</span>{q.note && <small>{q.note}</small>}</li>)}</ul>}
    {sent && <p className="saved-message"><Check size={14} /> {sent} The lab sees it now.</p>}
    {entry.status === 'booked' || entry.status === 'checked_in'
      ? open
        ? <div className="lab-request-form">
            <ExamFields examType={examType} onExamType={setExamType} />
            <label>How urgently
              <select value={urgency} onChange={(e) => setUrgency(e.target.value as Urgency)}>
                <option value="urgent">Urgent (today)</option><option value="soon">Soon (within 3 days)</option><option value="routine">Routine</option>
              </select>
            </label>
            <textarea aria-label="Note for the lab" value={note} maxLength={500} rows={2} onChange={(e) => setNote(e.target.value)} placeholder="For the lab: what to test and why (not shown to the patient)" />
            <div className="request-actions">
              <button type="button" className="button button-primary" disabled={busy} onClick={send}>{busy ? <Loader2 className="spin" size={16} /> : null}Send to the lab</button>
              <button type="button" className="text-button" onClick={() => setOpen(false)}>Cancel</button>
            </div>
          </div>
        : <button type="button" className="button button-secondary" onClick={() => setOpen(true)}><TestTube2 size={15} /> Request a test</button>
      : null}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}
