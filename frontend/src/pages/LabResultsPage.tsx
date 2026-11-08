import { useEffect, useRef, useState } from 'react'
import { FileUp, FlaskConical, Search } from 'lucide-react'
import { ErrorBanner } from '../components'
import { labResultsForPatient, loadLabResults, parseLabCsv, saveLabResults, type LabResult } from '../labResults'
import { DEMO_ACCOUNTS } from '../auth'
import { NavLink } from 'react-router-dom'

const MAX_FILE_SIZE = 1_000_000

const PATIENTS = DEMO_ACCOUNTS
  .filter((account) => account.role === 'patient')
  .map((account) => ({ id: account.id, name: `Patient ${String(account.id).padStart(4, '0')}` }))

function patientLabel(result: LabResult): string {
  if (result.patientName && result.patientId) return `${result.patientName} · ID ${result.patientId}`
  if (result.patientName) return result.patientName
  return `Patient ID ${result.patientId}`
}

export function LabResultsPage({ canUpload, patientId, patientEmail, overview = false }: { canUpload: boolean; patientId?: number; patientEmail?: string; overview?: boolean }) {
  const [results, setResults] = useState<LabResult[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [selectedPatientId, setSelectedPatientId] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    try {
      setResults(loadLabResults())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Saved lab results could not be loaded.')
    } finally {
      setLoaded(true)
    }
  }, [])

  async function uploadFile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    if (!selectedPatientId || !selectedFile) {
      setError('Choose a patient and a lab result file before uploading.')
      return
    }
    if (selectedFile.size > MAX_FILE_SIZE) {
      setError('Choose a file smaller than 1 MB.')
      return
    }

    const patient = PATIENTS.find((item) => String(item.id) === selectedPatientId)
    if (!patient) {
      setError('Choose a valid patient.')
      return
    }

    setUploading(true)
    try {
      const uploadedAt = new Date().toISOString()
      const isCsv = selectedFile.name.toLowerCase().endsWith('.csv') || selectedFile.type === 'text/csv'
      const uploaded = isCsv
        ? parseLabCsv(await selectedFile.text(), selectedFile.name, uploadedAt, patient)
        : [{
            id: `${uploadedAt}-${Math.random().toString(36).slice(2, 8)}`,
            patientId: String(patient.id),
            patientName: patient.name,
            fileName: selectedFile.name,
            uploadedAt,
            values: {},
            fileDataUrl: await readFileAsDataUrl(selectedFile),
          }]
      const updated = [...uploaded, ...results]
      saveLabResults(updated)
      setResults(updated)
      setSelectedFile(null)
      if (fileInput.current) fileInput.current.value = ''
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The file could not be uploaded.')
    } finally {
      setUploading(false)
    }
  }

  const patientView = patientId !== undefined && patientEmail !== undefined
  const accountResults = patientView ? labResultsForPatient(results, patientId, patientEmail) : results
  const search = query.trim().toLowerCase()
  const visible = accountResults.filter((result) =>
    `${patientLabel(result)} ${result.fileName} ${Object.entries(result.values).flat().join(' ')}`
      .toLowerCase().includes(search))

  return <>
    <div className={`welcome-row ${overview ? 'lab-overview-heading' : ''}`}>
      <div>
        {!overview && !canUpload && <div className="eyebrow"><FlaskConical size={14} /> {patientView ? 'YOUR CARE' : 'LAB WORKSPACE'}</div>}
        <h1>{overview ? 'Laboratory Data Records' : canUpload ? 'Upload Lab Results' : patientView ? 'Your lab results' : 'Lab results'}</h1>
        {!canUpload && <p>{overview ? 'Review all previously uploaded lab results across patients.' : patientView ? 'Review lab results shared with your account by the laboratory team.' : 'Review lab data shared by the laboratory team.'}</p>}
      </div>
      {overview && <NavLink className="button button-primary lab-overview-upload" to="/lab-results"><FileUp size={16} />Upload lab results</NavLink>}
      {!canUpload && !overview && <div className="lab-result-count">{accountResults.length} result{accountResults.length === 1 ? '' : 's'}</div>}
    </div>

    {canUpload && <section className="panel lab-upload-panel">
      <div className="lab-upload-icon"><FileUp size={20} /></div>
      <div className="lab-upload-copy">
        <h2>Select the patient's name and choose a file to upload.</h2>
        <p>CSV, PDF and JPG file types are supported. Files are limited to 1 MB.</p>
        <form className="lab-upload-form" onSubmit={(event) => void uploadFile(event)}>
          <label className="lab-upload-field">
            <span>Patient</span>
            <select value={selectedPatientId} disabled={!loaded || uploading} onChange={(event) => setSelectedPatientId(event.target.value)} required>
              <option value="">Select a patient</option>
              {PATIENTS.map((patient) => <option key={patient.id} value={patient.id}>{patient.name}</option>)}
            </select>
          </label>
          <label className="lab-upload-field">
            <span>Lab result file</span>
            <input ref={fileInput} type="file" disabled={!loaded || uploading} onChange={(event) => setSelectedFile(event.currentTarget.files?.[0] ?? null)} required />
          </label>
          <button className="button button-primary" type="submit" disabled={!loaded || uploading || !selectedPatientId || !selectedFile}>
            {uploading ? 'Uploading…' : 'Upload result'}
          </button>
        </form>
      </div>
    </section>}

    {error && <ErrorBanner>{error}</ErrorBanner>}
    {!canUpload && <div className="lab-results-toolbar">
      <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search patient, ID, or result" aria-label="Search lab results" /></div>
    </div>}

    {!canUpload && <section className="lab-results-list" aria-label="Uploaded lab results">
      {!loaded && <div className="panel empty-state">Loading lab results…</div>}
      {loaded && visible.map((result) => (
        <article className="panel lab-result-card" key={result.id}>
          <div className="lab-result-heading">
            <div className="lab-result-avatar"><FlaskConical size={17} /></div>
            <div><h2>{patientLabel(result)}</h2><p>{result.fileName} · Uploaded {new Date(result.uploadedAt).toLocaleString()}</p>
              {result.fileDataUrl && <a className="lab-result-file-link" href={result.fileDataUrl} target="_blank" rel="noreferrer">Open uploaded file</a>}
            </div>
          </div>
          {Object.keys(result.values).length > 0 && <dl className="lab-result-values">
            {Object.entries(result.values).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '—'}</dd></div>)}
          </dl>}
        </article>
      ))}
      {loaded && visible.length === 0 && <div className="panel empty-state">
        {accountResults.length
          ? 'No lab results match your search.'
          : patientView
            ? 'No lab results have been uploaded for your account yet.'
            : canUpload
              ? 'No lab results uploaded yet.'
              : 'No lab results have been shared yet.'}
      </div>}
    </section>}
  </>
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string'
      ? resolve(reader.result)
      : reject(new Error('The selected file could not be read.'))
    reader.onerror = () => reject(new Error('The selected file could not be read.'))
    reader.readAsDataURL(file)
  })
}
