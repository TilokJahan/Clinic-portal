import { useEffect, useState } from 'react'
import { NavLink, useSearchParams } from 'react-router-dom'
import { Activity, ArrowRight, Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { AiLabel, ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime } from '../format'
import type { MyAppointment, TriageRecord } from '../types'

const MAX = 4000

export function IntakePage() {
  const [params] = useSearchParams()
  const [bookings, setBookings] = useState<MyAppointment[] | null>(null)
  const [appointmentId, setAppointmentId] = useState(Number(params.get('appointment')) || 0)
  useEffect(() => {
    api.myAppointments().then((r) => {
      // Offer only upcoming visits that don't have an intake yet
      const open = r.ok ? r.data.filter((a) => !a.intake_submitted && Date.parse(a.starts_at) > Date.now()) : []
      setBookings(open)
      setAppointmentId((current) => current || open[0]?.id || 0)
    })
  }, [])
  const [symptoms, setSymptoms] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<TriageRecord | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!symptoms.trim()) { setError('Please describe your symptoms.'); return }
    setBusy(true)
    setError('')
    const response = await api.submitIntake(appointmentId, symptoms.trim())
    setBusy(false)
    if (response.ok) setResult(response.data)
    else setError(response.status === 409 && response.detail === 'Intake already submitted'
      ? 'You have already sent symptoms for this appointment. Your care team has them.'
      : response.detail)
  }

  const header = <div className="welcome-row"><div><div className="eyebrow">CLOUD CLINIC</div><h1>Tell us how you’re feeling</h1><p>A few details help your care team prepare for your visit.</p></div></div>

  if (result) return <>{header}
    <div className="panel form-panel triage-result">
      <h2>Thanks, your care team has it</h2>
      <p>A clinician will review this before your visit and makes all care decisions.</p>
      <div className="ai-summary"><div className="ai-title"><AiLabel /></div>
        <div className="result-urgency"><span className="drawer-label">SUGGESTED PRIORITY</span><UrgencyPill urgency={result.urgency} /></div>
        <p>{result.summary}</p>
        {result.suggested_specialty && <span>Suggested specialty · <b>{result.suggested_specialty}</b></span>}
      </div>
      {result.red_flags.length > 0 && <div className="red-flag-box"><b><Activity size={15} /> Warning signs noted</b>{result.red_flags.map((f) => <span key={f}>• {f}</span>)}</div>}
      {result.urgency === 'urgent' && <ErrorBanner>If you think this may be an emergency, call your local emergency number now. Don’t wait for your appointment.</ErrorBanner>}
      <NavLink to="/" className="button button-primary">Back to home <ArrowRight size={16} /></NavLink>
    </div></>

  if (bookings === null) return <>{header}<div className="panel form-panel empty-state"><Loader2 className="spin" size={18} /> Loading your appointments…</div></>

  if (!appointmentId) return <>{header}
    <div className="panel form-panel success-panel"><h2>Book a visit first</h2><p>Symptoms are sent with an appointment, so your care team can prepare for it.</p>
      <NavLink to="/book" className="button button-primary">Book an appointment <ArrowRight size={16} /></NavLink></div></>

  return <>{header}
    <form className="panel form-panel intake-form" onSubmit={submit}>
      <label>Appointment
        <select value={appointmentId} onChange={(e) => setAppointmentId(Number(e.target.value))}>
          {bookings.every((b) => b.id !== appointmentId) && <option value={appointmentId}>Appointment #{appointmentId}</option>}
          {bookings.map((b) => <option key={b.id} value={b.id}>{b.provider_name}, {formatDateTime(b.starts_at)}</option>)}
        </select>
      </label>
      <label>Describe your symptoms
        <textarea value={symptoms} onChange={(e) => setSymptoms(e.target.value)} maxLength={MAX} placeholder="When did it start? What does it feel like? Is it getting better or worse?" rows={6} required />
        <span className="field-hint">Please don’t include your name, phone number or other personal details. {symptoms.length}/{MAX}</span>
      </label>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      <div className="intake-disclaimer"><ShieldCheck size={17} /><p><b>This is not a diagnosis.</b> An AI suggests a priority and a clinician reviews it and makes all care decisions. If you may be experiencing an emergency, call your local emergency number.</p></div>
      <button disabled={busy} className="button button-primary submit-button">{busy ? <><Loader2 className="spin" size={16} /> Sending…</> : <>Send to care team <ArrowRight size={16} /></>}</button>
    </form></>
}
