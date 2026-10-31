import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, FlaskConical, Loader2, ShieldCheck, Upload } from 'lucide-react'
import { api } from './api'
import { AiLabel, ErrorBanner, UrgencyPill } from './components'
import { formatDateTime } from './format'
import type { LabFlag, LabReport, LabResult } from './types'

const ACCEPT = 'application/pdf,image/png,image/jpeg'
const MAX_BYTES = 10 * 1024 * 1024

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
  const load = useCallback(async () => {
    const result = await api.labReports(appointmentId)
    setReports(result.ok ? result.data : [])
  }, [appointmentId])
  useEffect(() => { void load() }, [load, refreshKey])
  return { reports, load }
}

/** Patient: upload a lab report for an appointment and see it once a clinician has approved it. */
export function PatientLabCard({ appointmentId }: { appointmentId: number }) {
  const { reports, load } = useLabReports(appointmentId, null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
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
    if (!ACCEPT.split(',').includes(file.type)) { setError('Please choose a PDF, PNG or JPEG file.'); return }
    if (file.size > MAX_BYTES) { setError('That file is over 10 MB.'); return }
    setBusy(true)
    const result = await api.uploadLabReport(appointmentId, file)
    setBusy(false)
    if (input.current) input.current.value = ''
    if (!result.ok) { setError(result.detail); return }
    await load()
  }

  return <div className="panel lab-card">
    <div className="lab-card-head"><div className="info-icon mint"><FlaskConical /></div><div><h3>Lab results</h3>
      <p>Have a recent lab report? Attach it (PDF or photo) and your care team will review it with your visit.</p></div></div>
    {reports?.map((r) => <PatientReport key={r.id} report={r} />)}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <label className={`button button-secondary upload-button ${busy ? 'disabled' : ''}`}>
      {busy ? <Loader2 className="spin" size={16} /> : <Upload size={16} />} {busy ? 'Uploading…' : 'Attach a lab report'}
      <input ref={input} type="file" accept={ACCEPT} hidden disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
    </label>
    <span className="field-hint">Only upload your own synthetic test reports. Max 10 MB.</span>
  </div>
}

function PatientReport({ report }: { report: LabReport }) {
  if (!report.explanation_approved) {
    const text = report.status === 'processing' ? 'Reading your report…'
      : report.status === 'failed' ? 'We could not read this report. Your care team will look at it.'
      : 'Received. Your care team is reviewing it.'
    return <div className="lab-status"><FileText size={15} /> <span>Report from {formatDateTime(report.uploaded_at)}: {text}</span></div>
  }
  return <div className="lab-approved">
    <div className="lab-status"><ShieldCheck size={15} /> <span>Reviewed by your care team</span></div>
    <p>{report.patient_explanation}</p>
    <table className="lab-table"><thead><tr><th>Test</th><th>Your result</th><th>Usual range</th><th></th></tr></thead>
      <tbody>{report.results.map((r, i) => <tr key={i}><td>{r.display_name}</td><td>{value(r)}</td><td>{range(r)}</td><td><LabFlagPill flag={r.flag} patient /></td></tr>)}</tbody>
    </table>
  </div>
}

/** Clinician (queue drawer): flagged results, summary, original file, approve the explanation. */
export function ClinicianLabSection({ appointmentId, refreshKey }: { appointmentId: number; refreshKey: unknown }) {
  const { reports } = useLabReports(appointmentId, refreshKey)
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
    <div className="lab-section-head"><span className="drawer-label"><FlaskConical size={13} /> LAB REPORT · {formatDateTime(report.uploaded_at)}</span>
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
