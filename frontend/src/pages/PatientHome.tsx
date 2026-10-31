import { NavLink } from 'react-router-dom'
import { ArrowRight, CalendarDays, HeartPulse, ShieldCheck } from 'lucide-react'
import { formatDateTime } from '../format'
import { bookingsFor } from '../session'

export function PatientHome({ patientId }: { patientId: number }) {
  const upcoming = bookingsFor(patientId).filter((b) => Date.parse(b.startsAt) > Date.now())
  return <>
    <div className="patient-hero"><div><div className="eyebrow">CLOUD CLINIC</div><h1>Your health, <em>in good hands.</em></h1><p>Book your next visit or tell us what’s going on. We’ll help your care team prepare.</p>
      <div className="hero-actions"><NavLink className="button button-primary" to="/book">Book an appointment <ArrowRight size={16} /></NavLink><NavLink className="button button-secondary" to="/intake">Share symptoms</NavLink></div></div>
      <div className="hero-art"><div className="art-circle"><div className="art-cross">+</div><HeartPulse size={78} strokeWidth={1.15} /></div><div className="art-card">Care team ready</div></div></div>
    <section className="patient-info-grid">
      <div className="panel patient-info"><div className="info-icon mint"><CalendarDays /></div><h3>Your next step</h3>
        {upcoming.length
          ? <><p>Next visit: {upcoming[upcoming.length - 1].providerName}, {formatDateTime(upcoming[upcoming.length - 1].startsAt)}.</p><NavLink to="/intake">Describe your symptoms <ArrowRight size={15} /></NavLink></>
          : <><p>No upcoming appointments. Find a time that works for you.</p><NavLink to="/book">Browse appointments <ArrowRight size={15} /></NavLink></>}
      </div>
      <div className="panel patient-info"><div className="info-icon lavender"><ShieldCheck /></div><h3>A note about symptom intake</h3><p>Your answers help the care team prepare. They don’t replace a medical evaluation.</p><NavLink to="/intake">Start an intake <ArrowRight size={15} /></NavLink></div>
    </section>
  </>
}
