import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Activity, ArrowRight, CalendarDays, Check, Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { AiLabel, ErrorBanner, UrgencyPill } from '../components'
import { formatDateTime, formatTime, nextWeekday, timeZoneName, todayInput } from '../format'
import { CLINIC_PHONE, SlotChoices, TimeframeChips } from '../Scheduling'
import type { Appointment, Assessment, Slot, Timeframe, TimeframeAvailability } from '../types'

type Mode = 'timeframe' | 'day'
const MAX_SYMPTOMS = 4000

/** Booking in three steps: 1. describe symptoms (the AI suggests a priority, which decides how
 *  soon the visit must be), 2. choose a time that fits, 3. request it. A clinician then
 *  approves the request, or proposes other times. */
export function BookingPage() {
  const [symptoms, setSymptoms] = useState('')
  const [assessing, setAssessing] = useState(false)
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [error, setError] = useState('')
  const [booked, setBooked] = useState<{ appointment: Appointment; slot: Slot } | null>(null)

  async function assess(e: React.FormEvent) {
    e.preventDefault()
    if (!symptoms.trim()) { setError('Please describe your symptoms.'); return }
    setAssessing(true)
    setError('')
    const r = await api.assess(symptoms.trim())
    setAssessing(false)
    if (r.ok) setAssessment(r.data)
    else setError(r.detail)
  }

  if (booked) return <><Header />
    <div className="panel form-panel success-panel"><div className="success-mark"><Check /></div>
      <h2>Request sent</h2>
      <p>{booked.slot.provider_name}, {formatDateTime(booked.slot.starts_at)}. We’re holding this time for you.</p>
      <p>A clinician will review your symptoms and how urgent they are, then confirm the visit or propose other times. You’ll see the answer on your home page.</p>
      <p className="field-hint">If you think this may be an emergency, call your local emergency number now.</p>
      <div className="hero-actions centered">
        <NavLink className="button button-primary" to="/">Go to home <ArrowRight size={16} /></NavLink>
        <button className="button button-secondary" onClick={() => { setBooked(null); setAssessment(null); setSymptoms('') }}>Request another visit</button>
      </div>
    </div></>

  return <><Header />
    <form className="panel form-panel" onSubmit={assess}>
      <div className="form-step"><span>01</span><div><h2>Describe your symptoms</h2><p>This decides how soon you should be seen, and so which times you can choose.</p></div></div>
      {!assessment
        ? <>
          <label className="booking-symptoms">
            <textarea aria-label="Describe your symptoms" value={symptoms} onChange={(e) => setSymptoms(e.target.value)} maxLength={MAX_SYMPTOMS} rows={5} required
              placeholder="When did it start? What does it feel like? Is it getting better or worse?" />
            <span className="field-hint">Please don’t include your name, phone number or other personal details. {symptoms.length}/{MAX_SYMPTOMS}</span>
          </label>
          <div className="intake-disclaimer"><ShieldCheck size={17} /><p><b>This is not a diagnosis.</b> An AI suggests a priority and a clinician reviews it and makes all care decisions. If you may be experiencing an emergency, call your local emergency number.</p></div>
          {error && <ErrorBanner>{error}</ErrorBanner>}
          <div className="form-footer"><span><ShieldCheck size={15} /> Your information is kept private.</span>
            <button className="button button-primary" disabled={assessing || !symptoms.trim()}>
              {assessing ? <><Loader2 className="spin" size={16} /> Checking…</> : <>Continue <ArrowRight size={16} /></>}
            </button>
          </div>
        </>
        : <AssessmentResult assessment={assessment} onEdit={() => setAssessment(null)} />}
    </form>
    {assessment && <TimeStep assessment={assessment} onBooked={setBooked} />}</>
}

function AssessmentResult({ assessment, onEdit }: { assessment: Assessment; onEdit: () => void }) {
  const t = assessment.triage
  return <div className="booking-assessment">
    <div className="ai-summary"><div className="ai-title"><AiLabel /></div>
      <div className="result-urgency"><span className="drawer-label">SUGGESTED PRIORITY</span><UrgencyPill urgency={t.urgency} /></div>
      <p>{t.summary}</p>
    </div>
    {t.red_flags.length > 0 && <div className="red-flag-box"><b><Activity size={15} /> Warning signs noted</b>{t.red_flags.map((f) => <span key={f}>• {f}</span>)}</div>}
    {t.urgency === 'urgent' && <ErrorBanner>If you think this may be an emergency, call your local emergency number now. Don’t wait for your appointment.</ErrorBanner>}
    <button type="button" className="text-button" onClick={onEdit}>Change my symptoms</button>
  </div>
}

function TimeStep({ assessment, onBooked }: { assessment: Assessment; onBooked: (b: { appointment: Appointment; slot: Slot }) => void }) {
  const priority = assessment.triage.urgency
  const limit = assessment.max_within_hours
  const urgent = priority === 'urgent'
  const [mode, setMode] = useState<Mode>('timeframe')
  const [timeframes, setTimeframes] = useState<Timeframe[]>([])
  const [availability, setAvailability] = useState<TimeframeAvailability[] | null>(null)
  const [within, setWithin] = useState<number | null>(null)
  const [date, setDate] = useState(nextWeekday)
  const [providerId, setProviderId] = useState(0)
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [chosen, setChosen] = useState<Slot | null>(null)
  // Nothing at all is free within the priority's limit: the first free time after it
  const [next, setNext] = useState<Slot | null>(null)
  const [booking, setBooking] = useState(false)
  const [error, setError] = useState('')

  const loadAvailability = useCallback(async () => {
    const [m, a] = await Promise.all([api.urgencyMatrix(), api.timeframeAvailability(priority)])
    if (m.ok) setTimeframes(m.data.timeframes)
    if (a.ok) {
      setAvailability(a.data)
      // Start with the longest allowed timeframe that has a free time
      const usable = a.data.filter((t) => t.allowed && t.free > 0)
      setWithin((w) => (w && usable.some((t) => t.hours === w) ? w : usable[usable.length - 1]?.hours ?? null))
    }
  }, [priority])
  useEffect(() => { void loadAvailability() }, [loadAvailability])
  const nothingInTime = availability !== null && !availability.some((t) => t.allowed && t.free > 0)

  const load = useCallback(async () => {
    setSlots(null)
    setNext(null)
    if (mode === 'timeframe') {
      if (nothingInTime) {
        const later = await api.nextAvailable(Math.min(limit, 336), providerId || undefined, urgent)
        setSlots([])
        const fallback = later.ok ? later.data : null
        setNext(fallback)
        setChosen(fallback)
        return
      }
      if (within === null) return
      const r = await api.earliestSlots(within, undefined, urgent)
      if (r.ok) { setSlots(r.data); setChosen(r.data.find((s) => !providerId || s.provider_id === providerId) ?? null) }
      else { setSlots([]); setError(r.detail) }
    } else {
      const r = await api.getSlots(date, undefined, { includeBooked: true, urgent })
      if (r.ok) { setSlots(r.data); setChosen(null) } else { setSlots([]); setError(r.detail) }
    }
  }, [mode, within, date, providerId, nothingInTime, limit, urgent])
  useEffect(() => { setError(''); void load() }, [load])

  const providers = useMemo(() => {
    const seen = new Map<number, string>()
    slots?.forEach((s) => seen.set(s.provider_id, `${s.provider_name} · ${s.specialty}`))
    return [...seen]
  }, [slots])
  const visible = slots?.filter((s) => !providerId || s.provider_id === providerId) ?? []
  const latest = Date.now() + limit * 3_600_000
  const tooLate = (s: Slot) => !nothingInTime && Date.parse(s.starts_at) > latest

  async function request() {
    if (!chosen) return
    setBooking(true)
    setError('')
    const r = await api.book(chosen.id, { assessmentId: assessment.triage.id })
    setBooking(false)
    if (r.ok) onBooked({ appointment: r.data, slot: chosen })
    else if (r.status === 409 && r.detail !== 'Please describe your symptoms again') {
      setError(r.detail === 'Slot has already started' ? 'That time has already started. Please pick a later one.'
        : r.detail.startsWith('That time is kept free') ? r.detail : 'That time was just taken. Please pick another.')
      setChosen(null)
      void loadAvailability()
      void load()
    } else setError(r.detail)
  }

  const allowedLabel = timeframes.find((t) => t.hours === limit)?.label.toLowerCase() ?? 'in the next two weeks'
  const providerSelect = <label className="date-choice">
    <select aria-label="Provider" value={providerId} onChange={(e) => setProviderId(Number(e.target.value))}>
      <option value={0}>Any provider</option>
      {providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
    </select>
  </label>

  return <div className="panel form-panel">
    <div className="form-step"><span>02</span><div><h2>Choose a time</h2>
      <p>With this priority you should be seen <b>{allowedLabel}</b>. <NavLink to="/priority">How is this decided?</NavLink> Times are in your time zone ({timeZoneName(mode === 'day' ? `${date}T12:00:00` : new Date())}).</p></div></div>
    <div className="filter-tabs booking-mode" role="tablist" aria-label="How to choose a time">
      <button role="tab" aria-selected={mode === 'timeframe'} className={mode === 'timeframe' ? 'active' : ''} onClick={() => setMode('timeframe')}>Earliest in a timeframe</button>
      <button role="tab" aria-selected={mode === 'day'} className={mode === 'day' ? 'active' : ''} onClick={() => setMode('day')}>Pick a day</button>
    </div>
    {mode === 'timeframe'
      ? <>
        <TimeframeChips timeframes={timeframes} value={within} max={limit} availability={availability ?? undefined} onChange={setWithin} />
        <div className="booking-filters">{providerSelect}</div>
      </>
      : <div className="booking-filters">
          <label className="date-choice"><CalendarDays size={18} />
            <input type="date" aria-label="Appointment date" value={date} min={todayInput()} onChange={(e) => setDate(e.target.value)} required />
          </label>
          {providerSelect}
        </div>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {slots === null
      ? <div className="empty-state"><Loader2 className="spin" size={18} /> Loading times…</div>
      : mode === 'timeframe'
        ? nothingInTime
          ? <div className="nothing-in-time">
              {urgent
                ? <div className="urgent-help" role="alert"><b>No time is free in the next 24 hours.</b>
                    <span>Please don’t wait for a visit: go to an urgent care centre or call the clinic at <a href={CLINIC_PHONE.href}>{CLINIC_PHONE.label}</a>. If this may be an emergency, call your local emergency number now.</span></div>
                : <p className="schedule-warning">No time is free {allowedLabel}. You can request the first free time; your care team will see it’s later than recommended.</p>}
              {next
                ? <><span className="drawer-label">EARLIEST AVAILABLE · LATER THAN RECOMMENDED</span><SlotChoices slots={[next]} chosen={chosen} onChoose={setChosen} /></>
                : <p className="field-hint">There are no free times at all right now. Please call the clinic at <a href={CLINIC_PHONE.href}>{CLINIC_PHONE.label}</a>.</p>}
            </div>
          : visible.length === 0
            ? <div className="empty-state">No free times with this provider in this timeframe. Try another provider.</div>
            : <SlotChoices slots={visible} chosen={chosen} onChoose={setChosen} />
        : visible.length === 0
          ? <div className="empty-state">No visits on this day. Try another date.</div>
          : <>
            <div className="slot-legend"><span><i className="dot free" /> Free</span><span><i className="dot booked" /> Booked or not available</span></div>
            <div className="slot-grid">{visible.map((slot) => {
              const late = tooLate(slot)
              const off = slot.available === false || late
              return <button type="button" key={slot.id} disabled={off} aria-pressed={chosen?.id === slot.id}
                className={`slot-button ${chosen?.id === slot.id ? 'chosen' : ''} ${off ? 'unavailable' : ''}`} onClick={() => setChosen(slot)}
                title={slot.available === false ? (slot.reserved ? 'Kept for urgent care' : 'Already booked') : late ? 'Later than your priority allows' : undefined}>
                <b>{formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
                {off && <small className="slot-state">{slot.available === false ? (slot.reserved ? 'Urgent care only' : 'Booked') : 'Too late for your priority'}</small>}
              </button>
            })}</div>
          </>}
    <div className="form-footer"><span><ShieldCheck size={15} /> The time is held while a clinician reviews your request.</span>
      <button disabled={!chosen || booking} className="button button-primary" onClick={request}>
        {booking ? <><Loader2 className="spin" size={16} /> Sending…</> : <>03 · Request this time <ArrowRight size={16} /></>}
      </button>
    </div>
  </div>
}

function Header() {
  return <div className="welcome-row"><div><h1>Book an appointment</h1><p>Tell us what’s going on, choose a time that fits, and a clinician confirms your visit.</p></div></div>
}
