import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ArrowRight, CalendarDays, ClipboardCheck, FlaskConical, Loader2, MessageSquareText, TestTube2 } from 'lucide-react'
import { api } from '../api'
import { UrgencyPill } from '../components'
import { dayIsOver, formatDateTime } from '../format'
import { EXAM_LABELS, NEED_LABEL } from '../labTypes'
import type { MyAppointment } from '../types'

/** The patient's visits: upcoming ones with their status, and past ones with what the visit
 *  was about, the tests, and the doctor's summary. Live, like the home page. */
export function MyAppointmentsPage() {
  const [items, setItems] = useState<MyAppointment[] | null>(null)
  const [tab, setTab] = useState<'upcoming' | 'past'>('upcoming')
  useEffect(() => api.subscribeMyAppointments(setItems, () => {}), [])

  const isPast = (a: MyAppointment) => a.status === 'completed' || dayIsOver(a.starts_at)
  const upcoming = (items ?? []).filter((a) => !isPast(a))
  const past = (items ?? []).filter(isPast).reverse()
  const shown = tab === 'upcoming' ? upcoming : past

  return <>
    <div className="welcome-row"><div><h1>My appointments</h1><p>Your upcoming visits, and summaries of the ones you’ve had.</p></div>
      <NavLink className="button button-primary" to="/book">Book a visit <ArrowRight size={16} /></NavLink></div>
    <div className="filter-tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'upcoming'} className={tab === 'upcoming' ? 'active' : ''} onClick={() => setTab('upcoming')}>Upcoming<span>{upcoming.length}</span></button>
      <button role="tab" aria-selected={tab === 'past'} className={tab === 'past' ? 'active' : ''} onClick={() => setTab('past')}>Past<span>{past.length}</span></button>
    </div>
    {items === null && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading your appointments…</div>}
    {items && shown.length === 0 && <div className="panel empty-state">{tab === 'upcoming' ? 'No upcoming visits. Book one when you need it.' : 'No past visits yet.'}</div>}
    <div className="visit-list">{shown.map((a) => <VisitCard key={a.id} visit={a} past={tab === 'past'} />)}</div>
  </>
}

function statusOf(a: MyAppointment, past: boolean): [string, string] {
  if (a.declined) return ['Not approved', 'bad']
  if (a.status === 'completed') return ['Completed', 'ok']
  if (past) return ['Past', 'muted']
  if (a.approved === false) return ['Waiting for approval', 'wait']
  return ['Confirmed', 'ok']
}

function VisitCard({ visit, past }: { visit: MyAppointment; past: boolean }) {
  const [label, tone] = statusOf(visit, past)
  const needs = visit.lab_needs ?? []
  const requests = visit.lab_requests ?? []
  const open = !past && !visit.declined && visit.status !== 'completed'
  return <article className="panel visit-card">
    <header className="visit-head">
      <div className="info-icon mint"><CalendarDays /></div>
      <div><h3>{formatDateTime(visit.starts_at)}</h3><p>{visit.provider_name} · {visit.specialty}</p></div>
      <span className={`visit-status ${tone}`}>{label}</span>
    </header>
    {visit.reason_summary && <section className="visit-part">
      <span className="drawer-label"><MessageSquareText size={13} /> WHAT THE VISIT IS ABOUT</span>
      <p>{visit.reason_summary}</p>
      {visit.priority && <p className="field-hint">Priority <UrgencyPill urgency={visit.priority} /></p>}
    </section>}
    {(needs.length > 0 || requests.length > 0 || (visit.lab_report_count ?? 0) > 0) && <section className="visit-part">
      <span className="drawer-label"><TestTube2 size={13} /> TESTS</span>
      <ul className="need-list">
        {requests.map((q) => <li key={`q${q.id}`} className={`need ${q.status === 'completed' ? 'ok' : 'info'}`}>
          <b>{EXAM_LABELS[q.exam_type]}</b><span>{q.status === 'completed' ? 'Done' : q.status === 'scheduled' ? 'Scheduled at the lab' : `Requested by your care team (${q.urgency})`}</span></li>)}
        {needs.filter((n) => !requests.some((q) => q.exam_type === n.exam_type)).map((n) =>
          <li key={n.exam_type} className={`need ${n.status === 'recent' ? 'ok' : n.status === 'requested' ? 'info' : 'warn'}`}><b>{EXAM_LABELS[n.exam_type]}</b><span>{NEED_LABEL[n.status]}</span></li>)}
      </ul>
      {(visit.lab_report_count ?? 0) > 0 && <p className="field-hint"><FlaskConical size={13} /> {visit.lab_report_count} result{visit.lab_report_count === 1 ? '' : 's'} on file. <NavLink to="/lab-results">See results</NavLink></p>}
    </section>}
    {visit.visit_summary && <section className="visit-part visit-summary">
      <span className="drawer-label"><ClipboardCheck size={13} /> YOUR DOCTOR’S SUMMARY{visit.completed_at ? ` · ${formatDateTime(visit.completed_at)}` : ''}</span>
      <p>{visit.visit_summary}</p>
    </section>}
    {visit.declined && <p className="field-hint">{visit.decline_reason ? `Your care team says: “${visit.decline_reason}”` : 'Your care team couldn’t confirm this time.'} <NavLink to="/book">Request another time</NavLink></p>}
    {open && <div className="visit-actions">
      {!visit.intake_submitted && <NavLink to={`/intake?appointment=${visit.id}`}>Describe your symptoms <ArrowRight size={14} /></NavLink>}
      <NavLink to={`/schedule?appointment=${visit.id}`}>Change the time <ArrowRight size={14} /></NavLink>
    </div>}
    {past && visit.status !== 'completed' && !visit.declined && <p className="field-hint">No summary for this visit.</p>}
  </article>
}
