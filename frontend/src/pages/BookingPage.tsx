import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ArrowRight, CalendarDays, Check, Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner } from '../components'
import { formatDateTime, formatTime, nextWeekday, timeZoneName, todayInput } from '../format'
import { CLINIC_PHONE, SlotChoices, TimeframeChips } from '../Scheduling'
import type { Appointment, Slot, Timeframe } from '../types'

type Mode = 'timeframe' | 'day'

export function BookingPage() {
  const [mode, setMode] = useState<Mode>('timeframe')
  const [timeframes, setTimeframes] = useState<Timeframe[]>([])
  const [within, setWithin] = useState(168)
  const [date, setDate] = useState(nextWeekday)
  const [providerId, setProviderId] = useState(0)
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [chosen, setChosen] = useState<Slot | null>(null)
  // By timeframe, when nothing is free inside it: the first free time after it
  const [next, setNext] = useState<Slot | null>(null)
  const [booking, setBooking] = useState(false)
  const [error, setError] = useState('')
  const [booked, setBooked] = useState<{ appointment: Appointment; slot: Slot } | null>(null)

  useEffect(() => { api.urgencyMatrix().then((r) => { if (r.ok) setTimeframes(r.data.timeframes) }) }, [])

  const load = useCallback(async () => {
    setSlots(null)
    setNext(null)
    const result = mode === 'timeframe' ? await api.earliestSlots(within) : await api.getSlots(date)
    if (result.ok) {
      setSlots(result.data)
      // By timeframe, the earliest time is proposed; the patient accepts it or picks another
      if (mode === 'timeframe') {
        const first = result.data.find((s) => !providerId || s.provider_id === providerId) ?? null
        const later = first ? null : await api.nextAvailable(within, providerId || undefined)
        const fallback = later?.ok ? later.data : null
        setNext(fallback)
        setChosen(first ?? fallback)
      }
    } else { setSlots([]); setError(result.detail) }
  }, [mode, within, date, providerId])

  useEffect(() => { setChosen(null); setError(''); if (mode === 'timeframe' || date) load() }, [mode, within, date, load])

  const providers = useMemo(() => {
    const seen = new Map<number, string>()
    slots?.forEach((s) => seen.set(s.provider_id, `${s.provider_name} · ${s.specialty}`))
    return [...seen]
  }, [slots])
  const visible = slots?.filter((s) => !providerId || s.provider_id === providerId) ?? []

  async function book() {
    if (!chosen) return
    setBooking(true)
    setError('')
    const result = await api.book(chosen.id)
    setBooking(false)
    if (result.ok) {
      setBooked({ appointment: result.data, slot: chosen })
    } else if (result.status === 409) {
      // Someone else got there first (or the time has passed): show it and refresh the list
      setError(result.detail === 'Slot has already started'
        ? 'That time has already started. Please pick a later one.'
        : 'That time was just taken. Please pick another.')
      setChosen(null)
      load()
    } else {
      setError(result.detail)
    }
  }

  if (booked) return <><Header />
    <div className="panel form-panel success-panel"><div className="success-mark"><Check /></div>
      <h2>You’re on the calendar</h2>
      <p>{booked.slot.provider_name}, {formatDateTime(booked.slot.starts_at)}. Appointment #{booked.appointment.id}.</p>
      <div className="hero-actions centered">
        <NavLink className="button button-primary" to={`/intake?appointment=${booked.appointment.id}`}>Describe your symptoms <ArrowRight size={16} /></NavLink>
        <button className="button button-secondary" onClick={() => { setBooked(null); setChosen(null); load() }}>Book another visit</button>
      </div>
    </div></>

  const providerSelect = <label className="date-choice">
    <select aria-label="Provider" value={providerId} onChange={(e) => setProviderId(Number(e.target.value))}>
      <option value={0}>Any provider</option>
      {providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
    </select>
  </label>

  return <><Header />
    <div className="panel form-panel">
      <div className="filter-tabs booking-mode" role="tablist" aria-label="How to choose a time">
        <button role="tab" aria-selected={mode === 'timeframe'} className={mode === 'timeframe' ? 'active' : ''} onClick={() => setMode('timeframe')}>Earliest in a timeframe</button>
        <button role="tab" aria-selected={mode === 'day'} className={mode === 'day' ? 'active' : ''} onClick={() => setMode('day')}>Pick a day</button>
      </div>
      {mode === 'timeframe'
        ? <>
          <div className="form-step"><span>01</span><div><h2>When do you need to be seen?</h2><p>We’ll propose the earliest free time; you accept it or pick another.</p></div></div>
          <TimeframeChips timeframes={timeframes} value={within} onChange={setWithin} />
          <div className="booking-filters">{providerSelect}</div>
        </>
        : <>
          <div className="form-step"><span>01</span><div><h2>Choose a date</h2><p>Weekday mornings, 30-minute visits</p></div></div>
          <div className="booking-filters">
            <label className="date-choice"><CalendarDays size={18} />
              <input type="date" aria-label="Appointment date" value={date} min={todayInput()} onChange={(e) => setDate(e.target.value)} required />
            </label>
            {providerSelect}
          </div>
        </>}
      <div className="form-step"><span>02</span><div><h2>{mode === 'timeframe' ? 'Accept a time' : 'Choose a time'}</h2><p>Times shown in your time zone ({timeZoneName(mode === 'day' ? `${date}T12:00:00` : new Date())})</p></div></div>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {slots === null
        ? <div className="empty-state"><Loader2 className="spin" size={18} /> Loading available times…</div>
        : visible.length === 0
          ? mode === 'timeframe'
            ? <div className="nothing-in-time">
                <p className="field-hint">No free times in this timeframe.</p>
                {next
                  ? <><span className="drawer-label">EARLIEST AVAILABLE</span><SlotChoices slots={[next]} chosen={chosen} onChoose={setChosen} /></>
                  : <p className="field-hint">There are no free times at all right now. Please call the clinic at <a href={CLINIC_PHONE.href}>{CLINIC_PHONE.label}</a>.</p>}
              </div>
            : <div className="empty-state">No free times on this day. Try another date.</div>
          : mode === 'timeframe'
            ? <SlotChoices slots={visible} chosen={chosen} onChoose={setChosen} />
            : <div className="slot-grid">{visible.map((slot) =>
                <button className={`slot-button ${chosen?.id === slot.id ? 'chosen' : ''}`} key={slot.id} onClick={() => setChosen(slot)} aria-pressed={chosen?.id === slot.id}>
                  <b>{formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
                </button>)}
              </div>}
      <div className="form-footer"><span><ShieldCheck size={15} /> Your information is kept private.</span>
        <button disabled={!chosen || booking} className="button button-primary" onClick={book}>
          {booking ? <><Loader2 className="spin" size={16} /> Booking…</> : <>{mode === 'timeframe' ? 'Accept this schedule' : 'Book this time'} <ArrowRight size={16} /></>}
        </button>
      </div>
    </div></>
}

function Header() {
  return <div className="welcome-row"><div><h1>Book an appointment</h1><p>Choose a time for your next visit.</p></div></div>
}
