import { useCallback, useEffect, useState } from 'react'
import { NavLink, useSearchParams } from 'react-router-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import { api } from '../api'
import { formatDateTime } from '../format'
import { OfferCard, ScheduleChooser } from '../Scheduling'
import type { MyAppointment } from '../types'

/** Change when an upcoming visit happens: answer a care-team offer, or pick a timeframe and time. */
export function ReschedulePage() {
  const [params] = useSearchParams()
  const [bookings, setBookings] = useState<MyAppointment[] | null>(null)
  const [appointmentId, setAppointmentId] = useState(Number(params.get('appointment')) || 0)
  // Changes only when the patient picks another visit, so a move keeps the chooser's message
  const [chooserKey, setChooserKey] = useState(0)

  const load = useCallback(async () => {
    const r = await api.myAppointments()
    const upcoming = r.ok ? r.data.filter((a) => a.status === 'booked' && Date.parse(a.starts_at) > Date.now()) : []
    setBookings(upcoming)
    setAppointmentId((current) => (upcoming.some((a) => a.id === current) ? current : upcoming[0]?.id ?? 0))
  }, [])
  useEffect(() => { void load() }, [load])

  const header = <div className="welcome-row"><div><h1>Change your visit time</h1><p>Choose when you’d like to come in. Your symptoms and lab reports stay with your visit.</p></div></div>
  if (bookings === null) return <>{header}<div className="panel form-panel empty-state"><Loader2 className="spin" size={18} /> Loading your appointments…</div></>
  if (!appointmentId) return <>{header}
    <div className="panel form-panel success-panel"><h2>No upcoming visits</h2><p>Book a visit first, then you can change its time here.</p>
      <NavLink to="/book" className="button button-primary">Book an appointment <ArrowRight size={16} /></NavLink></div></>

  const current = bookings.find((b) => b.id === appointmentId)
  return <>{header}
    {current?.pending_offer && <OfferCard appointment={current} onAnswered={() => { void load(); setChooserKey((k) => k + 1) }} />}
    <div className="panel form-panel">
      {bookings.length > 1 && <label className="schedule-pick">Visit
        <select value={appointmentId} onChange={(e) => { setAppointmentId(Number(e.target.value)); setChooserKey((k) => k + 1) }}>
          {bookings.map((b) => <option key={b.id} value={b.id}>{b.provider_name}, {formatDateTime(b.starts_at)}</option>)}
        </select>
      </label>}
      <ScheduleChooser key={chooserKey} appointmentId={appointmentId} onMoved={(moved) => {
        setBookings((old) => old?.map((b) => (b.id === appointmentId ? moved : b)).sort((x, y) => x.starts_at.localeCompare(y.starts_at)) ?? old)
        setAppointmentId(moved.id)
      }} />
    </div>
  </>
}
