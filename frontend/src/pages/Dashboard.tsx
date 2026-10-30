import { NavLink } from 'react-router-dom'
import { ArrowRight, Clock3, ShieldCheck, Sparkles, Users } from 'lucide-react'
import { Stat } from '../components'
import { formatWait, todayLong, waitMinutes } from '../format'
import { useQueue } from '../useQueue'
import { LiveBadge, QueueRow } from './QueuePage'

export function Dashboard() {
  const { queue, status } = useQueue()
  const items = queue ?? []
  const triaged = items.filter((e) => e.triage)
  const count = (u: string) => items.filter((e) => e.triage?.urgency === u).length
  const counts = { urgent: count('urgent'), soon: count('soon'), routine: count('routine') }
  const avgWait = triaged.length ? Math.round(triaged.reduce((sum, e) => sum + waitMinutes(e), 0) / triaged.length) : 0
  const reviewed = triaged.filter((e) => e.triage!.reviewed_at).length
  const pct = (n: number) => `${items.length ? (n / items.length) * 100 : 0}%`

  return <>
    <div className="welcome-row"><div><div className="eyebrow">{todayLong()}</div><h1>Good morning</h1><p>Here’s what’s happening at your clinic.</p></div></div>
    <section className="stat-grid">
      <Stat icon={<Users />} label="Waiting patients" value={String(items.length).padStart(2, '0')} note={`${items.length - triaged.length} still to send symptoms`} tone="mint" />
      <Stat icon={<ShieldCheck />} label="Needs attention" value={String(counts.urgent).padStart(2, '0')} note="urgent triage" tone="rose" />
      <Stat icon={<Clock3 />} label="Avg. wait since intake" value={formatWait(avgWait)} note="patients with an intake" tone="blue" />
      <Stat icon={<Sparkles />} label="Reviewed by a clinician" value={`${reviewed}/${triaged.length}`} note="AI suggestions decided" tone="lavender" />
    </section>
    <section className="content-grid">
      <div className="panel queue-panel">
        <div className="panel-heading"><div><div className="eyebrow"><LiveBadge status={status} /></div><h2>Patient queue</h2></div><NavLink className="text-link" to="/queue">View full queue <ArrowRight size={15} /></NavLink></div>
        <div className="queue-table"><div className="table-head"><span>PATIENT</span><span>AI SUMMARY</span><span>WAITING</span><span>TRIAGE</span></div>
          {items.slice(0, 4).map((e) => <QueueRow key={e.appointment_id} entry={e} compact />)}
          {queue === null && <div className="empty-state">Loading queue…</div>}
          {queue !== null && items.length === 0 && <div className="empty-state">Nobody is waiting right now.</div>}
        </div>
      </div>
      <div className="right-column">
        <div className="panel mix-panel"><div className="panel-heading"><div><div className="eyebrow">NOW</div><h2>Urgency mix</h2></div></div>
          <div className="mix-total"><b>{items.length}</b><span>patients in queue</span></div>
          <div className="mix-bar"><i className="bar-urgent" style={{ width: pct(counts.urgent) }} /><i className="bar-soon" style={{ width: pct(counts.soon) }} /><i className="bar-routine" style={{ width: pct(counts.routine) }} /></div>
          <div className="mix-legend"><span><i className="legend-dot urgent-dot" />Urgent <b>{counts.urgent}</b></span><span><i className="legend-dot soon-dot" />Soon <b>{counts.soon}</b></span><span><i className="legend-dot routine-dot" />Routine <b>{counts.routine}</b></span></div>
        </div>
        <div className="insight-card"><div className="insight-head"><span className="sparkle-icon"><Sparkles size={15} /></span><span>TO REVIEW</span></div>
          <p><b>{triaged.length - reviewed}</b> AI suggestion{triaged.length - reviewed === 1 ? '' : 's'} still waiting for a clinician decision.</p>
          <NavLink to="/queue">Open the queue <ArrowRight size={14} /></NavLink><div className="insight-orb" /></div>
      </div>
    </section>
    <div className="safety-note"><ShieldCheck size={15} /><span>AI triage is decision support only. Clinicians make all final care decisions.</span></div>
  </>
}
