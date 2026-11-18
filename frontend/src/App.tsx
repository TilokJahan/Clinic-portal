import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { CalendarCheck, CalendarDays, ClipboardList, FlaskConical, Gauge, HeartPulse, LayoutDashboard, LogOut, ShieldCheck, Stethoscope, TestTube2, UserCog, Users } from 'lucide-react'
import { AdminPage } from './pages/AdminPage'
import { BookingPage } from './pages/BookingPage'
import { BillingPage } from './pages/BillingPage'
import { Dashboard } from './pages/Dashboard'
import { IntakePage } from './pages/IntakePage'
import { InvitePage } from './pages/InvitePage'
import { LabRequestsPage } from './pages/LabRequestsPage'
import { LoginPage } from './pages/LoginPage'
import { LabResultsPage, PatientLabResultsPage } from './pages/LabResultsPage'
import { MyAppointmentsPage } from './pages/MyAppointmentsPage'
import { PatientHome } from './pages/PatientHome'
import { PhysicianPage } from './pages/PhysicianPage'
import { PriorityPage } from './pages/PriorityPage'
import { ReschedulePage } from './pages/ReschedulePage'
import { QueuePage } from './pages/QueuePage'
import { ScrollReveal } from './ScrollReveal'
import { useSession } from './session'
import type { Role } from './types'

const ROLE_LABEL: Record<Role, string> = {
  patient: 'Patient', clinician: 'Clinician', physician: 'Physician', lab_tech: 'Lab technician', admin: 'Admin',
}

function App() {
  const { session, setSession, signOut } = useSession()
  const location = useLocation()
  const navigate = useNavigate()

  if (!session) return <Routes><Route path="/login" element={<LoginPage onLogin={setSession} />} /><Route path="/invite/:token" element={<InvitePage onLogin={setSession} />} /><Route path="*" element={<Navigate to="/login" replace />} /></Routes>

  const { user } = session
  const role = user.role
  const admin = role === 'admin'
  // Who may use which part. Admins can open every staff page.
  const clinician = role === 'clinician' || admin
  const physician = role === 'physician' || admin
  const labTech = role === 'lab_tech' || admin
  const patient = role === 'patient'
  const switchAccount = () => { signOut(); navigate('/login') }
  const home = admin ? <AdminPage selfId={user.id} /> : role === 'clinician' ? <Dashboard /> : role === 'physician' ? <PhysicianPage /> : role === 'lab_tech' ? <LabRequestsPage /> : <PatientHome patientId={user.id} />

  return <div className={`app-shell ${patient ? 'patient-shell' : ''}`}>
    <header className="patient-banner">
      <NavLink className="patient-banner-brand" to="/" aria-label="Cloud Clinic home">
        <div className="brand-mark"><HeartPulse size={20} strokeWidth={2.4} /></div>
        <span><b>Cloud Clinic</b><small>CARE THAT CONNECTS</small></span>
      </NavLink>
      <nav className="patient-banner-nav" aria-label={`${ROLE_LABEL[role]} navigation`}>
        {patient
          ? <>
              <NavLink to="/" end onClick={() => {
                if (location.pathname === '/') {
                  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
                  window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
                }
              }}><HeartPulse size={16} />Home</NavLink>
              <NavLink to="/book"><CalendarDays size={16} />Book</NavLink>
              <NavLink to="/appointments"><CalendarCheck size={16} />My appointments</NavLink>
              <NavLink to="/lab-results"><FlaskConical size={16} />Results</NavLink>
              <NavLink to="/priority"><Gauge size={16} />How priority works</NavLink>
            </>
          : <>
              {admin && <NavLink to="/" end><UserCog size={16} />Users</NavLink>}
              {role === 'clinician' && <NavLink to="/" end><LayoutDashboard size={16} />Overview</NavLink>}
              {clinician && <NavLink to="/queue"><Users size={16} />Patient queue</NavLink>}
              {role === 'physician' && <NavLink to="/" end><Stethoscope size={16} />My schedule</NavLink>}
              {(role === 'clinician' || role === 'physician') && <NavLink to="/lab-requests"><TestTube2 size={16} />Lab requests</NavLink>}
              {admin && <NavLink to="/physician"><Stethoscope size={16} />Schedules</NavLink>}
              {role === 'lab_tech' && <NavLink to="/" end><TestTube2 size={16} />Lab requests</NavLink>}
              {admin && <NavLink to="/lab-requests"><TestTube2 size={16} />Lab requests</NavLink>}
              {labTech && <NavLink to="/lab-results"><ClipboardList size={16} />Upload results</NavLink>}
              <NavLink to="/priority"><Gauge size={16} />Priority matrix</NavLink>
            </>}
      </nav>
      <nav className="patient-banner-login" aria-label="Account navigation">
        <span className="patient-banner-user">{patient ? `Patient ${user.id}` : ROLE_LABEL[role]}</span>
        <button className="patient-banner-switch-user" type="button" onClick={switchAccount}><LogOut size={15} />Switch user</button>
      </nav>
    </header>
    <main className="main-area">
      <div className="page-content"><ScrollReveal key={location.pathname}><Routes>
        <Route path="/" element={home} />
        <Route path="/login" element={<LoginPage onLogin={setSession} />} />
        <Route path="/invite/:token" element={<InvitePage onLogin={setSession} />} />
        <Route path="/queue" element={clinician ? <QueuePage /> : <Navigate to="/" replace />} />
        <Route path="/physician" element={physician ? <PhysicianPage /> : <Navigate to="/" replace />} />
        <Route path="/lab-requests" element={labTech ? <LabRequestsPage /> : clinician || physician ? <LabRequestsPage readOnly /> : <Navigate to="/" replace />} />
        <Route path="/lab-results" element={labTech ? <LabResultsPage /> : patient ? <PatientLabResultsPage /> : <Navigate to="/" replace />} />
        <Route path="/book" element={patient ? <BookingPage /> : <Navigate to="/" replace />} />
        <Route path="/appointments" element={patient ? <MyAppointmentsPage /> : <Navigate to="/" replace />} />
        <Route path="/schedule" element={patient ? <ReschedulePage /> : <Navigate to="/" replace />} />
        <Route path="/priority" element={<PriorityPage />} />
        <Route path="/intake" element={patient ? <IntakePage /> : <Navigate to="/" replace />} />
        <Route path="/billing" element={patient ? <BillingPage patientId={user.id} /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes></ScrollReveal></div>
    </main>
    <footer className="app-demo-notice"><ShieldCheck size={15} aria-hidden="true" /><span>Synthetic demo data only. Do not enter real patient information.</span></footer>
  </div>
}

export default App
