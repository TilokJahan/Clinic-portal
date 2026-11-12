import { useEffect, useRef, useState } from 'react'
import { FileUp, FlaskConical, Loader2, RefreshCw, Search } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { api } from '../api'
import { ErrorBanner } from '../components'
import { formatDateTime } from '../format'
import { PatientLabCard } from '../LabPanels'
import { LAB_FILE_ACCEPT, labFileError } from '../labUpload'
import type { LabStatus, LabWorklistEntry, MyAppointment } from '../types'

const STATUS_LABELS: Record<LabStatus, string> = {
  processing: 'Processing', ready: 'Ready for clinician review', needs_review: 'Needs clinician review', failed: 'Processing failed',
}

export function LabResultsPage({ overview = false }: { overview?: boolean }) {
  // The worklist endpoint filters by UTC day; visit times themselves are shown locally.
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [worklist, setWorklist] = useState<LabWorklistEntry[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [appointmentId, setAppointmentId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      const result = await api.labWorklist(date)
      if (!active) return
      setLoading(false)
      if (!result.ok) {
        setError(result.detail)
        setWorklist([])
        setAppointmentId('')
        return
      }
      setError('')
      setWorklist(result.data)
      setAppointmentId((current) => result.data.some((entry) => String(entry.appointment_id) === current) ? current : '')
      if (result.data.some((entry) => entry.reports.some((report) => report.status === 'processing'))) {
        timer = setTimeout(() => { void load() }, 3000)
      }
    }
    setLoading(true)
    setError('')
    if (date) void load()
    else { setWorklist([]); setLoading(false) }
    return () => { active = false; clearTimeout(timer) }
  }, [date, refresh])

  async function uploadFile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (uploading || loading) return
    setUploadError('')
    setSuccess('')
    const appointment = worklist.find((entry) => String(entry.appointment_id) === appointmentId)
    if (!appointment || !file) { setUploadError('Choose a scheduled visit and a lab report.'); return }
    const problem = labFileError(file)
    if (problem) { setUploadError(problem); return }
    setUploading(true)
    const result = await api.uploadLabReportAsTech(appointment.appointment_id, file)
    setUploading(false)
    if (!result.ok) {
      setUploadError(result.detail)
      // The appointment may have been cancelled/completed since the list loaded.
      if (result.status === 404 || result.status === 409) setRefresh((value) => value + 1)
      return
    }
    setSuccess(`Report received for ${appointment.patient_label}. Your care team can review it when processing finishes.`)
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
    setRefresh((value) => value + 1)
  }

  const search = query.trim().toLowerCase()
  const visible = worklist.filter((entry) =>
    `${entry.patient_label} ${entry.appointment_id} ${entry.provider_name}`.toLowerCase().includes(search))

  return <>
    <div className={`welcome-row ${overview ? 'lab-overview-heading' : ''}`}>
      <div>
        <div className="eyebrow"><FlaskConical size={14} /> LAB WORKSPACE</div>
        <h1>{overview ? 'Laboratory Data Records' : 'Upload Lab Results'}</h1>
        <p>{overview ? 'Review scheduled visits and the status of uploaded reports.' : 'Attach a lab report to the correct scheduled visit.'}</p>
      </div>
      {overview && <NavLink className="button button-primary lab-overview-upload" to="/lab-results"><FileUp size={16} />Upload lab results</NavLink>}
    </div>

    <div className="lab-worklist-controls">
      <label className="lab-upload-field"><span>Visit date (UTC)</span><input type="date" value={date} disabled={uploading} onChange={(event) => {
        setDate(event.target.value)
        setWorklist([])
        setAppointmentId('')
        setLoading(true)
        setSuccess('')
        setUploadError('')
      }} /></label>
      <button className="button button-secondary" type="button" disabled={loading || uploading || !date} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={15} />Refresh</button>
      <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search patients, visits or providers" aria-label="Search lab worklist" /></div>
    </div>
    {error && <ErrorBanner>{error}</ErrorBanner>}

    {!overview && <section className="panel lab-upload-panel">
      <div className="lab-upload-icon"><FileUp size={20} /></div>
      <div className="lab-upload-copy">
        <h2>Select a scheduled visit and choose a file to upload.</h2>
        <p>PDF, PNG and JPEG files are supported, up to 10 MB.</p>
        <form className="lab-upload-form" onSubmit={(event) => void uploadFile(event)}>
          <label className="lab-upload-field"><span>Scheduled visit</span>
            <select value={appointmentId} disabled={loading || uploading || worklist.length === 0} onChange={(event) => { setAppointmentId(event.target.value); setSuccess(''); setUploadError('') }} required>
              <option value="">Select a visit</option>
              {worklist.map((entry) => <option key={entry.appointment_id} value={entry.appointment_id}>{entry.patient_label} · {formatDateTime(entry.starts_at)} · {entry.provider_name} · Visit #{entry.appointment_id}</option>)}
            </select>
          </label>
          <label className="lab-upload-field"><span>Lab report file</span>
            <input ref={fileInput} type="file" accept={LAB_FILE_ACCEPT} disabled={loading || uploading || worklist.length === 0} onChange={(event) => {
              const selected = event.currentTarget.files?.[0] ?? null
              const problem = selected ? labFileError(selected) : null
              setFile(problem ? null : selected)
              setUploadError(problem ?? '')
              setSuccess('')
              if (problem) event.currentTarget.value = ''
            }} required />
          </label>
          <button className="button button-primary" type="submit" disabled={loading || uploading || !appointmentId || !file}>
            {uploading && <Loader2 className="spin" size={15} />}{uploading ? 'Uploading…' : 'Upload result'}
          </button>
        </form>
        {uploadError && <ErrorBanner>{uploadError}</ErrorBanner>}
        {success && <p className="lab-upload-success" role="status">{success}</p>}
      </div>
    </section>}

    <section className="lab-results-list" aria-label="Scheduled visits and lab report status" aria-busy={loading}>
      {loading && <div className="panel empty-state"><Loader2 className="spin" size={18} />Loading scheduled visits…</div>}
      {!loading && !error && visible.map((entry) => <article className="panel lab-result-card" key={entry.appointment_id}>
        <div className="lab-result-heading"><div className="lab-result-avatar"><FlaskConical size={17} /></div>
          <div><h2>{entry.patient_label}</h2><p>{formatDateTime(entry.starts_at)} · {entry.provider_name} · Visit #{entry.appointment_id} · {entry.status === 'checked_in' ? 'Checked in' : 'Booked'}</p></div>
        </div>
        {entry.reports.length === 0 ? <p className="field-hint">No reports uploaded for this visit.</p> : <ul className="lab-worklist-reports">
          {entry.reports.map((report) => <li key={report.id}><span>Report #{report.id} · {formatDateTime(report.uploaded_at)}</span><b>{STATUS_LABELS[report.status]}</b></li>)}
        </ul>}
      </article>)}
      {!loading && !error && visible.length === 0 && <div className="panel empty-state">{!date ? 'Choose a visit date.' : worklist.length ? 'No visits match your search.' : 'No scheduled visits for this date. Choose another date.'}</div>}
    </section>
  </>
}

export function PatientLabResultsPage() {
  const [appointments, setAppointments] = useState<MyAppointment[] | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    setAppointments(null)
    setError('')
    api.myAppointments().then((result) => {
      if (!active) return
      if (result.ok) setAppointments(result.data)
      else { setAppointments([]); setError(result.detail) }
    })
    return () => { active = false }
  }, [refresh])
  return <>
    <div className="welcome-row"><div><div className="eyebrow">YOUR CARE</div><h1>Your lab results</h1><p>Reports are linked to your visits. Your care team reviews results before sharing them with you.</p></div></div>
    {error && <><ErrorBanner>{error}</ErrorBanner><button className="button button-secondary" onClick={() => setRefresh((value) => value + 1)}>Try again</button></>}
    {appointments === null && <div className="panel empty-state"><Loader2 className="spin" size={18} />Loading your visits…</div>}
    {appointments?.map((appointment) => <section key={appointment.id} className="patient-lab-visit"><h2>{appointment.provider_name} · {formatDateTime(appointment.starts_at)}</h2><PatientLabCard appointmentId={appointment.id} /></section>)}
    {!error && appointments?.length === 0 && <div className="panel empty-state">No visits yet. <NavLink to="/book">Book an appointment</NavLink> to attach a lab report.</div>}
  </>
}
