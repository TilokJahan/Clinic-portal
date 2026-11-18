import { useEffect, useState } from 'react'
import { CalendarCheck, Loader2, TestTube2 } from 'lucide-react'
import { api } from './api'
import { ErrorBanner, UrgencyPill } from './components'
import { formatDateTime, formatDay, formatTime } from './format'
import { EXAM_LABELS } from './labTypes'
import type { LabRequestSummary, LabTimes } from './types'

const WINDOW: Record<number, string> = { 24: 'within 24 hours', 72: 'within 3 days', 336: 'within 2 weeks' }

/** A test the care team asked for, from the patient's side: the lab's proposed times to accept,
 *  or another free lab time to choose; then the booked lab visit, which can still be moved. */
export function LabVisitCard({ request, onChanged }: { request: LabRequestSummary; onChanged?: () => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const [own, setOwn] = useState<LabTimes | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [moving, setMoving] = useState(false)
  const proposed = request.proposed_times ?? []
  useEffect(() => { setPicked(null); setOwn(null); setMoving(false); setError('') }, [request.status, request.scheduled_at, proposed.join()])

  async function book(at: string) {
    setBusy(true); setError('')
    const r = await api.scheduleLabVisit(request.id, at)
    setBusy(false)
    if (r.ok) { setOwn(null); setMoving(false); onChanged?.() } else setError(r.detail)
  }
  async function chooseOwn() {
    setError('')
    const r = await api.myLabTimes(request.id)
    if (r.ok) { setOwn(r.data); setPicked(null) } else setError(r.detail)
  }

  const label = EXAM_LABELS[request.exam_type]
  const choosing = own !== null
  const options = choosing ? own!.times : proposed
  return <section className="panel offer-card lab-visit-card" aria-label={`${label} at the lab`}>
    <div className="info-icon mint"><TestTube2 /></div>
    <div>
      <h3>{label} at the lab <UrgencyPill urgency={request.urgency} /></h3>
      {request.status === 'requested' && <p>Your care team asked for a {label.toLowerCase()}. The lab will send you times to come in shortly.</p>}
      {request.status === 'scheduled' && request.scheduled_at && !moving && <>
        <p className="lab-visit-time"><CalendarCheck size={15} /> Booked: <b>{formatDateTime(request.scheduled_at)}</b>. Please come to the lab at that time.</p>
        <button type="button" className="text-button" onClick={() => { setMoving(true); void chooseOwn() }}>Change the time</button>
      </>}
      {(request.status === 'proposed' || moving) && <>
        <p>{choosing
          ? <>Free lab times {own!.in_time ? WINDOW[own!.within_hours] ?? 'in time' : '(nothing is free in time, so these are the first free ones)'}:</>
          : <>The lab proposed {proposed.length === 1 ? 'a time' : `${proposed.length} times`} for your {label.toLowerCase()}. Accept one, or choose another time.</>}</p>
        {options.length > 0 && <div className="time-chips" role="radiogroup" aria-label="Lab times">{options.map((t) =>
          <button type="button" role="radio" aria-checked={picked === t} key={t} className={`review-choice ${picked === t ? 'chosen' : ''}`} onClick={() => setPicked(t)}>
            {formatDay(t)} · {formatTime(t)}</button>)}</div>}
        <div className="schedule-actions">
          <button type="button" className="button button-primary" disabled={!picked || busy} onClick={() => picked && book(picked)}>
            {busy ? <Loader2 className="spin" size={16} /> : null}{picked ? `Book ${formatDay(picked)}, ${formatTime(picked)}` : 'Choose a time above'}
          </button>
          {!choosing && <button type="button" className="button button-secondary" onClick={chooseOwn}>Choose another time</button>}
          {choosing && proposed.length > 0 && request.status === 'proposed' && <button type="button" className="text-button" onClick={() => { setOwn(null); setPicked(null) }}>Back to the lab’s times</button>}
          {moving && <button type="button" className="text-button" onClick={() => { setMoving(false); setOwn(null) }}>Keep my booking</button>}
        </div>
      </>}
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </div>
  </section>
}

/** Open lab requests the patient has to act on or come to, from a list of their visits. */
export const openLabRequests = (requests: LabRequestSummary[] | undefined) =>
  (requests ?? []).filter((q) => q.status === 'requested' || q.status === 'proposed' || q.status === 'scheduled')
