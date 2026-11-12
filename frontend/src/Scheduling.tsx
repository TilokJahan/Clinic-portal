import { useCallback, useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { CalendarClock, Check, Info, Loader2 } from 'lucide-react'
import { api } from './api'
import { ErrorBanner, UrgencyPill } from './components'
import { formatDateTime, formatDay, formatTime } from './format'
import type { MyAppointment, QueueEntry, ScheduleOptions, Slot, Timeframe } from './types'

const conflictMessage = (detail: string) =>
  detail === 'Slot has already started' ? 'That time has already started. Please pick another.' : 'That time was just taken. Please pick another.'

/** Timeframe buttons. Timeframes longer than `max` are shown but can't be chosen. */
export function TimeframeChips({ timeframes, value, max, onChange }: { timeframes: Timeframe[]; value: number | null; max?: number; onChange: (hours: number) => void }) {
  return <div className="timeframe-chips" role="radiogroup" aria-label="Timeframe">
    {timeframes.map((t) => {
      const allowed = max === undefined || t.hours <= max
      return <button type="button" role="radio" aria-checked={value === t.hours} key={t.hours} disabled={!allowed}
        className={`review-choice ${value === t.hours ? 'chosen' : ''}`} onClick={() => onChange(t.hours)}
        title={allowed ? undefined : 'Not available for your priority'}>{t.label}</button>
    })}
  </div>
}

/** Free times as buttons, the earliest one marked. */
export function SlotChoices({ slots, chosen, onChoose }: { slots: Slot[]; chosen: Slot | null; onChoose: (slot: Slot) => void }) {
  return <div className="slot-grid slot-options">{slots.map((slot, i) =>
    <button type="button" className={`slot-button slot-option ${chosen?.id === slot.id ? 'chosen' : ''}`} key={slot.id} onClick={() => onChoose(slot)} aria-pressed={chosen?.id === slot.id}>
      {i === 0 && <em>Earliest</em>}<b>{formatDay(slot.starts_at)} · {formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
    </button>)}
  </div>
}

/** The patient picks a timeframe, sees the free times in it and accepts one for this visit. */
export function ScheduleChooser({ appointmentId, onMoved }: { appointmentId: number; onMoved?: (moved: MyAppointment) => void }) {
  const [timeframes, setTimeframes] = useState<Timeframe[]>([])
  const [within, setWithin] = useState<number | undefined>(undefined)
  const [options, setOptions] = useState<ScheduleOptions | null>(null)
  const [chosen, setChosen] = useState<Slot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<{ moved: boolean; startsAt: string; provider?: string } | null>(null)
  const [id, setId] = useState(appointmentId)

  useEffect(() => { api.urgencyMatrix().then((r) => { if (r.ok) setTimeframes(r.data.timeframes) }) }, [])
  const load = useCallback(async () => {
    setOptions(null)
    const r = await api.scheduleOptions(id, within)
    if (r.ok) { setOptions(r.data); setChosen(r.data.slots[0] ?? null) } else setError(r.detail)
  }, [id, within])
  useEffect(() => { if (!done) void load() }, [load, done])

  async function accept() {
    if (!chosen) return
    setBusy(true)
    setError('')
    const r = await api.reschedule(id, chosen.id)
    setBusy(false)
    if (r.ok) { setDone({ moved: true, startsAt: r.data.starts_at, provider: r.data.provider_name }); setId(r.data.id); onMoved?.(r.data) }
    else if (r.status === 409) { setError(conflictMessage(r.detail)); void load() }
    else setError(r.detail)
  }

  if (done) return <div className="schedule-done" role="status"><Check size={18} />
    <div><b>{done.moved ? 'Your visit has moved' : 'You’re keeping your current time'}</b>
      <span>{done.provider ? `${done.provider}, ` : ''}{formatDateTime(done.startsAt)}.{done.moved ? ' Your symptoms and any lab reports moved with it.' : ''}</span>
      <button type="button" className="link-button" onClick={() => setDone(null)}>Choose a different time</button></div>
  </div>

  if (!options) return error ? <ErrorBanner>{error}</ErrorBanner> : <div className="empty-state"><Loader2 className="spin" size={18} /> Finding times…</div>
  const allowed = timeframes.find((t) => t.hours === options.max_within_hours)

  return <div className="schedule-chooser">
    <div className="schedule-note"><Info size={16} /><p>
      {options.priority && <>Your priority is <UrgencyPill urgency={options.priority} />. </>}
      {options.care_team_limit
        ? <>Your care team would like to see you <b>{allowed?.label.toLowerCase()}</b>.</>
        : <>You can choose a time <b>{allowed?.label.toLowerCase() ?? 'in the next two weeks'}</b>.</>}{' '}
      <NavLink to="/priority">How is this decided?</NavLink></p></div>
    <span className="drawer-label">WHEN WOULD YOU LIKE TO COME IN?</span>
    <TimeframeChips timeframes={timeframes} value={options.within_hours} max={options.max_within_hours} onChange={(h) => { setWithin(h); setError('') }} />
    <p className="schedule-current">Current visit: <b>{formatDateTime(options.starts_at)}</b>{' '}
      {options.current_fits
        ? <span className="fits-tag">within this timeframe</span>
        : <span className="fits-tag late">later than this timeframe</span>}</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {options.slots.length === 0
      ? <div className="empty-state">No free times in this timeframe. {options.within_hours < options.max_within_hours ? 'Try a longer one.' : 'Please call the clinic.'}</div>
      : <SlotChoices slots={options.slots} chosen={chosen} onChoose={setChosen} />}
    <div className="schedule-actions">
      {options.current_fits && <button type="button" className="button button-secondary" onClick={() => setDone({ moved: false, startsAt: options.starts_at })}>Keep my current time</button>}
      <button type="button" className="button button-primary" disabled={!chosen || busy} onClick={accept}>
        {busy ? <><Loader2 className="spin" size={16} /> Saving…</> : <>Accept this schedule{chosen ? `: ${formatDay(chosen.starts_at)}, ${formatTime(chosen.starts_at)}` : ''}</>}
      </button>
    </div>
  </div>
}

/** An earlier visit the care team offered. The patient accepts or keeps their time. */
export function OfferCard({ appointment, onAnswered }: { appointment: MyAppointment; onAnswered: () => void }) {
  const offer = appointment.pending_offer
  const [busy, setBusy] = useState<'accept' | 'decline' | null>(null)
  const [error, setError] = useState('')
  if (!offer) return null
  async function answer(kind: 'accept' | 'decline') {
    setBusy(kind)
    setError('')
    const r = kind === 'accept' ? await api.acceptOffer(offer!.id) : await api.declineOffer(offer!.id)
    setBusy(null)
    if (r.ok) onAnswered()
    else { setError(r.detail); if (r.status === 409) setTimeout(onAnswered, 2500) }
  }
  return <section className="panel offer-card" aria-labelledby={`offer-${offer.id}`}>
    <div className="info-icon mint"><CalendarClock /></div>
    <div>
      <h3 id={`offer-${offer.id}`}>Your care team offered an earlier visit</h3>
      <p><b>{offer.provider_name}, {formatDateTime(offer.starts_at)}</b> instead of {formatDateTime(appointment.starts_at)}. Nothing changes unless you accept.</p>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      <div className="schedule-actions">
        <button type="button" className="button button-secondary" disabled={busy !== null} onClick={() => answer('decline')}>{busy === 'decline' ? <Loader2 className="spin" size={16} /> : null}Keep my current time</button>
        <button type="button" className="button button-primary" disabled={busy !== null} onClick={() => answer('accept')}>{busy === 'accept' ? <Loader2 className="spin" size={16} /> : null}Accept the earlier visit</button>
      </div>
    </div>
  </section>
}

/** Clinician drawer: offer an urgent patient an earlier slot with the same provider. */
export function ClinicianOfferSection({ entry }: { entry: QueueEntry }) {
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [chosen, setChosen] = useState<Slot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState('')
  useEffect(() => { setSlots(null); setChosen(null); setError(''); setSent('') }, [entry.appointment_id])
  if (entry.status !== 'booked') return null

  async function find() {
    setError('')
    const r = await api.earlierSlots(entry.appointment_id)
    if (r.ok) { setSlots(r.data); setChosen(r.data[0] ?? null) } else setError(r.detail)
  }
  async function offer() {
    if (!chosen) return
    setBusy(true)
    setError('')
    const r = await api.offerEarlierVisit(entry.appointment_id, chosen.id)
    setBusy(false)
    if (r.ok) { setSent(formatDateTime(r.data.starts_at)); setSlots(null) } else setError(r.detail)
  }

  return <div className="drawer-section">
    <span className="drawer-label">EARLIER VISIT</span>
    {sent || entry.offer_pending
      ? <p><Check size={14} /> {sent ? `Offered ${sent}.` : 'An earlier visit was offered.'} Waiting for the patient to accept or keep their time.</p>
      : <>
        <p>{entry.needs_earlier_visit
          ? 'Urgent, but the visit is more than 24 hours away. Offer an earlier time; the patient decides.'
          : 'Offer the patient an earlier time with the same provider. Nothing moves until they accept.'}</p>
        {slots === null
          ? <button type="button" className="button button-secondary" onClick={find}>Find earlier times</button>
          : slots.length === 0
            ? <p className="field-hint">No earlier free times with {entry.provider_name}.</p>
            : <><SlotChoices slots={slots} chosen={chosen} onChoose={setChosen} />
              <button type="button" className="button button-primary" disabled={!chosen || busy} onClick={offer}>{busy ? <Loader2 className="spin" size={16} /> : null}Offer this time</button></>}
      </>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}
