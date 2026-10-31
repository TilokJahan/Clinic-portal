import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ArrowRight, CalendarDays, Check, Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner } from '../components'
import { formatDateTime, formatTime, nextWeekday, timeZoneName, todayInput } from '../format'
import { rememberBooking } from '../session'
import type { Appointment, Slot } from '../types'

export function BookingPage({ patientId }: { patientId: number }) {
  const [date, setDate] = useState(nextWeekday)
  const [providerId, setProviderId] = useState(0)
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [chosen, setChosen] = useState<Slot | null>(null)
  const [booking, setBooking] = useState(false)
  const [error, setError] = useState('')
  const [booked, setBooked] = useState<{ appointment: Appointment; slot: Slot } | null>(null)

  const load = useCallback(async () => {
    setSlots(null)
    const result = await api.getSlots(date)
    if (result.ok) setSlots(result.data)
    else { setSlots([]); setError(result.detail) }
  }, [date])

  useEffect(() => { setChosen(null); setError(''); if (date) load() }, [date, load])

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
    const result = await api.book(patientId, chosen.id)
    setBooking(false)
    if (result.ok) {
      rememberBooking({ appointmentId: result.data.id, patientId, startsAt: chosen.starts_at, providerName: chosen.provider_name })
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

  return <><Header />
    <div className="panel form-panel">
      <div className="form-step"><span>01</span><div><h2>Choose a date</h2><p>Weekday mornings, 30-minute visits</p></div></div>
      <div className="booking-filters">
        <label className="date-choice"><CalendarDays size={18} />
          <input type="date" aria-label="Appointment date" value={date} min={todayInput()} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <label className="date-choice">
          <select aria-label="Provider" value={providerId} onChange={(e) => { setProviderId(Number(e.target.value)); setChosen(null) }}>
            <option value={0}>Any provider</option>
            {providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
      </div>
      <div className="form-step"><span>02</span><div><h2>Choose a time</h2><p>Times shown in your time zone ({timeZoneName(`${date}T12:00:00`)})</p></div></div>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {slots === null
        ? <div className="empty-state"><Loader2 className="spin" size={18} /> Loading available times…</div>
        : visible.length === 0
          ? <div className="empty-state">No free times on this day. Try another date.</div>
          : <div className="slot-grid">{visible.map((slot) =>
              <button className={`slot-button ${chosen?.id === slot.id ? 'chosen' : ''}`} key={slot.id} onClick={() => setChosen(slot)} aria-pressed={chosen?.id === slot.id}>
                <b>{formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
              </button>)}
            </div>}
      <div className="form-footer"><span><ShieldCheck size={15} /> Your information is kept private.</span>
        <button disabled={!chosen || booking} className="button button-primary" onClick={book}>
          {booking ? <><Loader2 className="spin" size={16} /> Booking…</> : <>Book this time <ArrowRight size={16} /></>}
        </button>
      </div>
    </div></>
}

function Header() {
  return <div className="welcome-row"><div><div className="eyebrow">CLOUD CLINIC</div><h1>Book an appointment</h1><p>Choose a time for your next visit.</p></div></div>
}
