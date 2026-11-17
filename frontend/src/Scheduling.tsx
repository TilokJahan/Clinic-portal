import { useCallback, useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { CalendarClock, Check, Info, Loader2 } from 'lucide-react'
import { api } from './api'
import { ErrorBanner, UrgencyPill } from './components'
import { formatDateTime, formatDay, formatTime } from './format'
import type { MyAppointment, QueueEntry, ScheduleOptions, Slot, Timeframe, TimeframeAvailability } from './types'

const conflictMessage = (detail: string) =>
  detail === 'Slot has already started' ? 'That time has already started. Please pick another.'
    : detail.startsWith('That time is kept free') ? detail : 'That time was just taken. Please pick another.'

export const CLINIC_PHONE = { label: '800.123.4567', href: 'tel:+18001234567' }
const callClinic = <a href={CLINIC_PHONE.href}>{CLINIC_PHONE.label}</a>

/** Timeframe buttons. A timeframe longer than `max` (the priority's limit), or with no free time
 *  at all (`availability`), is shown greyed out and can't be chosen. */
export function TimeframeChips({ timeframes, value, max, availability, onChange }: { timeframes: Timeframe[]; value: number | null; max?: number; availability?: TimeframeAvailability[]; onChange: (hours: number) => void }) {
  return <div className="timeframe-chips" role="radiogroup" aria-label="Timeframe">
    {timeframes.map((t) => {
      const allowed = max === undefined || t.hours <= max
      const free = availability?.find((a) => a.hours === t.hours)?.free
      const full = free === 0
      const why = !allowed ? 'Not available for your priority' : full ? 'No free times in this timeframe' : undefined
      return <button type="button" role="radio" aria-checked={value === t.hours} key={t.hours} disabled={!allowed || full}
        className={`review-choice ${value === t.hours ? 'chosen' : ''}`} onClick={() => onChange(t.hours)} title={why}>
        {t.label}{allowed && full && <small className="chip-note">Fully booked</small>}
      </button>
    })}
  </div>
}

/** Pick up to `max` times (the clinician proposing several). */
export function SlotMultiChoices({ slots, chosen, max, onChange }: { slots: Slot[]; chosen: number[]; max: number; onChange: (ids: number[]) => void }) {
  return <div className="slot-grid slot-options">{slots.map((slot, i) => {
    const on = chosen.includes(slot.id)
    const full = !on && chosen.length >= max
    return <button type="button" key={slot.id} aria-pressed={on} disabled={full}
      className={`slot-button slot-option ${on ? 'chosen' : ''} ${slot.reserved ? 'reserved' : ''}`}
      onClick={() => onChange(on ? chosen.filter((id) => id !== slot.id) : [...chosen, slot.id])}>
      {i === 0 && <em>Earliest</em>}<b>{formatDay(slot.starts_at)} · {formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
      {slot.reserved && <small className="reserve-tag">Kept for urgent care</small>}
    </button>
  })}</div>
}

/** Free times as buttons, the earliest one marked. */
export function SlotChoices({ slots, chosen, onChoose }: { slots: Slot[]; chosen: Slot | null; onChoose: (slot: Slot) => void }) {
  return <div className="slot-grid slot-options">{slots.map((slot, i) =>
    <button type="button" className={`slot-button slot-option ${chosen?.id === slot.id ? 'chosen' : ''} ${slot.reserved ? 'reserved' : ''}`} key={slot.id} onClick={() => onChoose(slot)} aria-pressed={chosen?.id === slot.id}>
      {i === 0 && <em>Earliest</em>}<b>{formatDay(slot.starts_at)} · {formatTime(slot.starts_at)}</b><small>{slot.provider_name}</small>
      {slot.reserved && <small className="reserve-tag">Kept for urgent care</small>}
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
  const [availability, setAvailability] = useState<TimeframeAvailability[] | undefined>(undefined)

  useEffect(() => { api.urgencyMatrix().then((r) => { if (r.ok) setTimeframes(r.data.timeframes) }) }, [])
  const priority = options?.priority ?? null
  useEffect(() => { api.timeframeAvailability(priority).then((r) => { if (r.ok) setAvailability(r.data) }) }, [priority, done])
  const load = useCallback(async () => {
    setOptions(null)
    const r = await api.scheduleOptions(id, within)
    if (r.ok) { setOptions(r.data); setChosen(r.data.slots[0] ?? (soonerThanCurrent(r.data) ? r.data.next_available! : null)) } else setError(r.detail)
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
    <TimeframeChips timeframes={timeframes} value={options.within_hours} max={options.max_within_hours} availability={availability} onChange={(h) => { setWithin(h); setError('') }} />
    <p className="schedule-current">Current visit: <b>{formatDateTime(options.starts_at)}</b>{' '}
      {options.current_fits
        ? <span className="fits-tag">within this timeframe</span>
        : <span className="fits-tag late">later than this timeframe</span>}</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {options.slots.length === 0
      ? <NothingInTime options={options} allowedLabel={allowed?.label.toLowerCase() ?? 'in time'} chosen={chosen} onChoose={setChosen} />
      : <SlotChoices slots={options.slots} chosen={chosen} onChoose={setChosen} />}
    <div className="schedule-actions">
      {options.current_fits && <button type="button" className="button button-secondary" onClick={() => setDone({ moved: false, startsAt: options.starts_at })}>Keep my current time</button>}
      <button type="button" className="button button-primary" disabled={!chosen || busy} onClick={accept}>
        {busy ? <><Loader2 className="spin" size={16} /> Saving…</> : <>Accept this schedule{chosen ? `: ${formatDay(chosen.starts_at)}, ${formatTime(chosen.starts_at)}` : ''}</>}
      </button>
    </div>
  </div>
}

const soonerThanCurrent = (o: ScheduleOptions) => Boolean(o.next_available && o.next_available.starts_at < o.starts_at)

/** Nothing is free in the timeframe: never a dead end. Offer the next free time if it is sooner
 * than the current visit, and tell an urgent patient not to wait. */
function NothingInTime({ options, allowedLabel, chosen, onChoose }: { options: ScheduleOptions; allowedLabel: string; chosen: Slot | null; onChoose: (slot: Slot) => void }) {
  const next = options.next_available ?? null
  const longerAllowed = options.within_hours < options.max_within_hours
  const urgent = options.max_within_hours <= 24
  return <div className="nothing-in-time">
    {longerAllowed
      ? <p className="field-hint">No free times in this timeframe. Try a longer one, or take the next free time below.</p>
      : options.current_fits
        ? <p className="field-hint">No other free times in this timeframe. Your current visit already fits, so you can keep it.</p>
        : urgent
          ? <div className="urgent-help" role="alert"><b>No time is free in the next 24 hours.</b>
              <span>Please don’t wait for a visit: go to an urgent care centre or call the clinic at {callClinic}. If this may be an emergency, call your local emergency number now.</span>
              <span>Your care team can see this and may offer you a time.</span></div>
          : <p className="schedule-warning">No time is free {allowedLabel}. Your care team can see that your visit is later than recommended and may offer you a time. You can also call the clinic at {callClinic}.</p>}
    {next
      ? next.starts_at < options.starts_at
        ? <><span className="drawer-label">EARLIEST AVAILABLE · LATER THAN RECOMMENDED</span><SlotChoices slots={[next]} chosen={chosen} onChoose={onChoose} /></>
        : <p className="field-hint">The next free time is {formatDateTime(next.starts_at)}, which isn’t sooner than your current visit, so keep your current time.</p>
      : <p className="field-hint">There are no free times at all right now. Please call the clinic at {callClinic}.</p>}
  </div>
}

/** Times the care team proposed. The patient accepts one, chooses another time themselves (it
 *  then needs approval again), or says none of them work, with a reason the clinician reads. */
export function OfferCard({ appointment, onAnswered }: { appointment: MyAppointment; onAnswered: () => void }) {
  const offers = appointment.pending_offers?.length ? appointment.pending_offers : appointment.pending_offer ? [appointment.pending_offer] : []
  const [picked, setPicked] = useState<number | null>(null)
  const [declining, setDeclining] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'accept' | 'decline' | null>(null)
  const [error, setError] = useState('')
  const ids = offers.map((o) => o.id).join(',')
  useEffect(() => { setPicked(null); setDeclining(false); setNote(''); setError('') }, [ids])
  if (!offers.length) return null
  const chosen = offers.find((o) => o.id === picked) ?? (offers.length === 1 ? offers[0] : null)

  async function answer(kind: 'accept' | 'decline') {
    setBusy(kind)
    setError('')
    const r = kind === 'accept' ? await api.acceptOffer(chosen!.id) : await api.declineOffer(offers[0].id, note)
    setBusy(null)
    if (r.ok) onAnswered()
    else { setError(r.detail); if (r.status === 409) setTimeout(onAnswered, 2500) }
  }

  const many = offers.length > 1
  return <section className="panel offer-card" aria-labelledby={`offer-${appointment.id}`}>
    <div className="info-icon mint"><CalendarClock /></div>
    <div>
      <h3 id={`offer-${appointment.id}`}>{many ? `Your care team proposed ${offers.length} times` : 'Your care team proposed a time'}</h3>
      <p>Instead of {formatDateTime(appointment.starts_at)}. Nothing changes unless you accept.</p>
      <div className="offer-choices" role={many ? 'radiogroup' : undefined} aria-label="Proposed times">
        {offers.map((o) => <button type="button" key={o.id} role={many ? 'radio' : undefined} aria-checked={many ? chosen?.id === o.id : undefined}
          className={`slot-button slot-option ${chosen?.id === o.id ? 'chosen' : ''}`} onClick={() => setPicked(o.id)} disabled={!many}>
          <b>{formatDay(o.starts_at)} · {formatTime(o.starts_at)}</b><small>{o.provider_name}</small>
        </button>)}
      </div>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {declining
        ? <div className="request-actions">
            <textarea aria-label="Why these times don't work" value={note} maxLength={500} rows={2} onChange={(e) => setNote(e.target.value)}
              placeholder="Optional: tell your care team what would work, e.g. afternoons only." />
            <button type="button" className="button button-secondary" disabled={busy !== null} onClick={() => answer('decline')}>
              {busy === 'decline' ? <Loader2 className="spin" size={16} /> : null}Send to my care team
            </button>
            <button type="button" className="text-button" disabled={busy !== null} onClick={() => setDeclining(false)}>Back</button>
          </div>
        : <div className="schedule-actions">
            <button type="button" className="button button-primary" disabled={!chosen || busy !== null} onClick={() => answer('accept')}>
              {busy === 'accept' ? <Loader2 className="spin" size={16} /> : null}{chosen ? `Accept ${formatDay(chosen.starts_at)}, ${formatTime(chosen.starts_at)}` : 'Choose a time above'}
            </button>
            <NavLink className="button button-secondary" to={`/schedule?appointment=${appointment.id}`}>Choose another time myself</NavLink>
            <button type="button" className="text-button" disabled={busy !== null} onClick={() => setDeclining(true)}>None of these work</button>
          </div>}
    </div>
  </section>
}

/** Clinician drawer: propose up to three other times, with any doctor, within the patient's
 *  priority. Accepting one counts as approved. */
export function ClinicianOfferSection({ entry }: { entry: QueueEntry }) {
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [chosen, setChosen] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(0)
  useEffect(() => { setSlots(null); setChosen([]); setError(''); setSent(0) }, [entry.appointment_id])
  // A new answer from the patient (declined) reopens the section
  useEffect(() => { if (entry.offer_declined_note != null) setSent(0) }, [entry.offer_declined_note])
  if (entry.status !== 'booked') return null

  async function find() {
    setError('')
    const r = await api.alternativeSlots(entry.appointment_id)
    if (r.ok) { setSlots(r.data); setChosen(r.data[0] ? [r.data[0].id] : []) } else setError(r.detail)
  }
  async function propose() {
    if (!chosen.length) return
    setBusy(true)
    setError('')
    const r = await api.propose(entry.appointment_id, chosen)
    setBusy(false)
    if (r.ok) { setSent(r.data.length); setSlots(null); setChosen([]) } else setError(r.detail)
  }

  const waiting = sent > 0 || entry.offer_pending
  return <div className="drawer-section">
    <span className="drawer-label">PROPOSE OTHER TIMES</span>
    {entry.offer_declined_note != null && !waiting && <p className="declined-note">
      The patient said none of the proposed times work{entry.offer_declined_note ? <>: “{entry.offer_declined_note}”</> : '.'}</p>}
    {waiting
      ? <p><Check size={14} /> {sent ? `${sent} time${sent > 1 ? 's' : ''} proposed.` : 'Times were proposed.'} Waiting for the patient to choose one, pick their own, or reply.</p>
      : <>
        <p>{entry.needs_earlier_visit
          ? `The visit is later than a ${entry.urgency} priority allows (${entry.urgency === 'urgent' ? 'within 24 hours' : 'within 3 days'}). Propose earlier times or call the patient.`
          : 'Propose up to three times, with any doctor, that fit the priority. The patient chooses one, or tells you why none work.'}</p>
        {slots === null
          ? <button type="button" className="button button-secondary" onClick={find}>Find times</button>
          : slots.length === 0
            ? <p className="field-hint">No other free time fits this priority, with any doctor, including the urgent reserve.{entry.needs_earlier_visit ? ' Call the patient to arrange care sooner.' : ''}</p>
            : <><SlotMultiChoices slots={slots} chosen={chosen} max={3} onChange={setChosen} />
              <button type="button" className="button button-primary" disabled={!chosen.length || busy} onClick={propose}>
                {busy ? <Loader2 className="spin" size={16} /> : null}Propose {chosen.length || ''} time{chosen.length === 1 ? '' : 's'}
              </button></>}
      </>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}
