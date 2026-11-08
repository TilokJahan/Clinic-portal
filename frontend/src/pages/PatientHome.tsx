import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink } from 'react-router-dom'
import { Ambulance, ArrowDown, ArrowRight, Baby, Bean, Bone, Brain, CalendarDays, CalendarCheck, Ear, Heart, HeartPulse, MapPin, MessageCircle, Phone, ReceiptText, Ribbon, Salad, ScanFace, Send, ShieldCheck, Stethoscope, TestTube2 } from 'lucide-react'
import { formatDateTime } from '../format'
import { addPatientMessage, loadPatientMessages, type PatientMessage } from '../patientMessages'
import { api } from '../api'
import { PatientLabCard } from '../LabPanels'
import type { MyAppointment } from '../types'

const SERVICES = [
  { name: 'Primary care', description: 'Everyday care, checkups and prevention', icon: Stethoscope, offerings: ['Annual wellness visits', 'Preventive screenings', 'Chronic condition support'] },
  { name: 'Heart & circulation', description: 'Heart health, risk checks and follow-up', icon: Heart, offerings: ['Heart health assessments', 'Blood pressure support', 'Cardiology referrals'] },
  { name: 'Dermatology', description: 'Care for skin, hair and nail concerns', icon: ScanFace, offerings: ['Skin assessments', 'Acne and rash care', 'Dermatology referrals'] },
  { name: 'Digestive health', description: 'Care for digestive concerns and gut health', icon: Salad, offerings: ['Digestive health visits', 'Nutrition guidance', 'Specialist referrals'] },
  { name: 'Cancer care', description: 'Screening guidance and coordinated cancer care', icon: Ribbon, offerings: ['Screening recommendations', 'Care coordination', 'Specialist referrals'] },
  { name: 'Children’s care', description: 'Well-child visits and pediatric support', icon: Baby, offerings: ['Well-child checkups', 'Growth and development', 'Everyday pediatric concerns'] },
  { name: 'Ear, nose & throat', description: 'Help with common head and neck concerns', icon: Ear, offerings: ['Ear and hearing concerns', 'Sinus and allergy support', 'Throat and voice concerns'] },
  { name: 'Neurology', description: 'Assessment for brain, spine and nerve concerns', icon: Brain, offerings: ['Headache assessment', 'Neurological consultations', 'Specialist referrals'] },
  { name: 'Nephrology', description: 'Care for kidney health and related conditions', icon: Bean, offerings: ['Kidney health assessments', 'Chronic kidney care', 'Nephrology referrals'] },
  { name: 'Obstetrics & Gynecology', description: 'Routine, reproductive and life-stage care', icon: WomanIcon, offerings: ['Routine wellness visits', 'Reproductive health', 'Preventive screenings'] },
  { name: 'Orthopaedics', description: 'Support for movement, muscles and joints', icon: Bone, offerings: ['Joint and muscle concerns', 'Mobility assessments', 'Orthopedic referrals'] },
  { name: 'Urgent care', description: 'Timely assessment when a health concern arises', icon: Ambulance, offerings: ['Same-week appointments', 'New or worsening symptoms', 'Care-team follow-up'] },
]

function WomanIcon({ size, strokeWidth }: { size?: number; strokeWidth?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.5 21v-2.1c0-1.3 1-2.3 3-3.1l2.2-.9a5.5 5.5 0 0 1-1.9-4.1V7.6a4.2 4.2 0 0 1 8.4 0v3.2a5.5 5.5 0 0 1-1.9 4.1l2.2.9c2 .8 3 1.8 3 3.1V21" />
    <path d="M8 9.5c1.2-.2 2.1-.8 2.7-1.7 1.2 1 2.9 1.6 5.3 1.7M9.5 12a2.5 2.5 0 0 0 5 0M8.2 16.3c1.1 1 2.4 1.5 3.8 1.5s2.7-.5 3.8-1.5M4.5 19.5c4.5 1.6 10.5 1.6 15 0" />
  </svg>
}

const PATIENT_TOOLS = [
  { title: 'Message your doctor', description: 'Send a message to your clinic team.', icon: MessageCircle, to: null, action: 'message' },
  { title: 'View lab results', description: 'Check results shared with you by your care team.', icon: TestTube2, to: '/lab-results' },
  { title: 'Manage your appointments', description: 'Choose a time for your next clinic visit.', icon: CalendarCheck, to: '/book' },
  { title: 'Billing and statements', description: 'Review billing information and payment options.', icon: ReceiptText, to: '/billing' },
]

export function PatientHome({ patientId }: { patientId: number }) {
  const [expandedService, setExpandedService] = useState<string | null>(null)
  const [messageOpen, setMessageOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState<PatientMessage[]>([])
  const [messageError, setMessageError] = useState('')
  const [messageSent, setMessageSent] = useState(false)
  const messageSection = useRef<HTMLElement>(null)
  const [upcoming, setUpcoming] = useState<MyAppointment[]>([])
  useEffect(() => {
    api.myAppointments().then((r) => { if (r.ok) setUpcoming(r.data.filter((a) => Date.parse(a.starts_at) > Date.now())) })
  }, [patientId])
  const next = upcoming[0]

  useEffect(() => {
    if (messageOpen) messageSection.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [messageOpen])

  useEffect(() => {
    try {
      setMessages(loadPatientMessages().filter((item) => item.patientId === patientId))
    } catch (reason) {
      setMessageError(reason instanceof Error ? reason.message : 'Saved messages could not be loaded.')
    }
  }, [patientId])

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessageError('')
    setMessageSent(false)
    try {
      const updated = addPatientMessage(patientId, message)
      setMessages(updated.filter((item) => item.patientId === patientId))
      setMessage('')
      setMessageSent(true)
    } catch (reason) {
      setMessageError(reason instanceof Error ? reason.message : 'Your message could not be saved.')
    }
  }

  return <>
    <div className="patient-hero"><div className="patient-hero-inner"><div><div className="eyebrow">CLOUD CLINIC</div><h1>Your health, <em>in good hands.</em></h1><p>Book your next visit or tell us what’s going on. We’ll help your care team prepare.</p>
      <div className="hero-actions"><NavLink className="button button-primary" to="/book">Book an appointment <ArrowRight size={16} /></NavLink><NavLink className="button button-secondary" to="/intake">Share symptoms</NavLink></div></div>
      <div className="hero-art"><HeartPulse className="hero-heartbeat" size={270} strokeWidth={1.35} aria-hidden="true" /></div></div></div>
    <section className="patient-info-grid">
      <div className="panel patient-info"><div className="info-icon mint"><CalendarDays /></div><h3>Your next step</h3>
        {next
          ? <><p>Next visit: {next.provider_name}, {formatDateTime(next.starts_at)}.{next.intake_submitted ? ' Your care team has your symptoms.' : ''}</p>
              {!next.intake_submitted && <NavLink to={`/intake?appointment=${next.id}`}>Describe your symptoms <ArrowRight size={15} /></NavLink>}</>
          : <><p>No upcoming appointments. Find a time that works for you.</p><NavLink to="/book">Browse appointments <ArrowRight size={15} /></NavLink></>}
      </div>
      <div className="panel patient-info"><div className="info-icon lavender"><ShieldCheck /></div><h3>A note about symptom intake</h3><p>Your answers help the care team prepare. They don’t replace a medical evaluation.</p><NavLink to="/intake">Start an intake <ArrowRight size={15} /></NavLink></div>
    </section>
    {next && <PatientLabCard appointmentId={next.id} />}
    <section className="patient-tools" aria-labelledby="patient-tools-title">
      <div className="patient-tools-heading">
        <div className="eyebrow">YOUR CARE, MADE SIMPLE</div>
        <h2 id="patient-tools-title">Manage your care</h2>
        <p>Quick access to services for your care journey.</p>
      </div>
      <div className="patient-tools-grid">
        {PATIENT_TOOLS.map(({ title, description, icon: Icon, to, action }) => {
          const content = <>
            <span className="patient-tool-icon"><Icon size={25} strokeWidth={1.7} /></span>
            <span className="patient-tool-copy"><b>{title}</b><span>{description}</span></span>
            {to || action ? <ArrowRight className="patient-tool-arrow" size={17} /> : <span className="patient-tool-status">Coming soon</span>}
          </>
          return action === 'message'
            ? <button className="patient-tool" type="button" aria-expanded={messageOpen} aria-controls="message-doctor" onClick={() => setMessageOpen(true)} key={title}>{content}</button>
            : to
            ? <NavLink className="patient-tool" to={to} key={title}>{content}</NavLink>
            : <article className="patient-tool patient-tool-unavailable" key={title}>{content}</article>
        })}
      </div>
    </section>
    {messageOpen && <section className="panel patient-message-panel" id="message-doctor" aria-labelledby="message-doctor-title" ref={messageSection}>
      <div className="info-icon mint"><MessageCircle /></div>
      <div className="patient-message-heading">
        <h2 id="message-doctor-title">Message your doctor</h2>
      </div>
      <form className="patient-message-form" onSubmit={sendMessage}>
        <label htmlFor="patient-message">Your message</label>
        <textarea id="patient-message" value={message} maxLength={2000} onChange={(event) => { setMessage(event.target.value); setMessageSent(false) }} placeholder="How can your care team help?" required />
        <div className="patient-message-actions">
          <span>{message.length}/2000 characters</span>
          <button className="button button-primary" type="submit"><Send size={15} />Send message</button>
        </div>
        {messageError && <p className="patient-message-status error">{messageError}</p>}
        {messageSent && <p className="patient-message-status success">Your message has been saved for your care team.</p>}
      </form>
      {messages.length > 0 && <div className="patient-message-history">
        <h3>Messages you’ve sent</h3>
        {messages.map((item) => <article className="patient-message-item" key={item.id}>
          <p>{item.message}</p><time dateTime={item.sentAt}>{new Date(item.sentAt).toLocaleString()}</time>
        </article>)}
      </div>}
    </section>}
    <section className="clinic-services" aria-labelledby="clinic-services-title">
      <div className="services-heading">
        <div>
          <h2 id="clinic-services-title">Explore our services</h2>
          <p>Find the care and support you need, all in one place.</p>
        </div>
      </div>
      <div className="services-grid">
        {SERVICES.map(({ name, description, icon: Icon, offerings }) => {
          const expanded = expandedService === name
          const listId = `services-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
          return <article className={`service-card ${expanded ? 'service-card-expanded' : ''}`} key={name}>
            <div className="service-icon"><Icon size={23} strokeWidth={1.7} /></div>
            <h3>{name}</h3>
            <p>{description}</p>
            <button
              className="service-toggle"
              type="button"
              aria-expanded={expanded}
              aria-controls={listId}
              onClick={() => setExpandedService(expanded ? null : name)}
            >
              {expanded ? 'Hide services' : 'Show services'}
              <ArrowDown size={15} className={expanded ? 'service-chevron-open' : ''} />
            </button>
            {expanded && <ul className="service-offerings" id={listId}>
              {offerings.map((offering) => <li key={offering}>{offering}</li>)}
            </ul>}
          </article>
        })}
      </div>
    </section>
    <footer className="patient-footer">
      <div className="patient-footer-contact">
        <div className="patient-footer-item"><MapPin size={19} /><span><b>Visit us</b><span>1903 W Michigan Ave, Kalamazoo, MI 49008</span></span></div>
        <a className="patient-footer-item" href="tel:+18001234567"><Phone size={19} /><span><b>Call us</b><span>800.123.4567</span></span></a>
        <span className="patient-footer-copyright">© {new Date().getFullYear()} Cloud Clinic. All rights reserved.</span>
      </div>
    </footer>
  </>
}
