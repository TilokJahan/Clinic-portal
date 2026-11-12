import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { CalendarDays, FlaskConical, Gauge, HeartPulse, LayoutDashboard, LogOut, ShieldCheck, Users } from 'lucide-react'
import { BookingPage } from './pages/BookingPage'
import { BillingPage } from './pages/BillingPage'
import { Dashboard } from './pages/Dashboard'
import { IntakePage } from './pages/IntakePage'
import { LoginPage } from './pages/LoginPage'
import { LabResultsPage, PatientLabResultsPage } from './pages/LabResultsPage'
import { PatientHome } from './pages/PatientHome'
import { PriorityPage } from './pages/PriorityPage'
import { ReschedulePage } from './pages/ReschedulePage'
import { QueuePage } from './pages/QueuePage'
import { ScrollReveal } from './ScrollReveal'
import { useSession } from './session'

function App() {
  const { session, setSession, signOut } = useSession()
  const location = useLocation()
  const navigate = useNavigate()

  if (!session) return <Routes><Route path="/login" element={<LoginPage onLogin={setSession} />} /><Route path="*" element={<Navigate to="/login" replace />} /></Routes>

  const { user } = session
  const clinician = user.role === 'clinician' || user.role === 'admin'
  const labTech = user.role === 'lab_tech'
  const labAccess = labTech || user.role === 'admin'
  const patient = !clinician && !labTech
  const roleLabel = clinician ? 'Clinician' : labTech ? 'Lab Tech' : 'Patient'
  const switchAccount = () => { signOut(); navigate('/login') }

  return <div className={`app-shell ${patient ? 'patient-shell' : ''}`}>
    <header className="patient-banner">
      <NavLink className="patient-banner-brand" to="/" aria-label="Cloud Clinic home">
        <div className="brand-mark"><HeartPulse size={20} strokeWidth={2.4} /></div>
        <span><b>Cloud Clinic</b><small>CARE THAT CONNECTS</small></span>
      </NavLink>
      <nav className="patient-banner-nav" aria-label={`${roleLabel} navigation`}>
        {clinician
          ? <>
              <NavLink to="/" end><LayoutDashboard size={16} />Overview</NavLink>
              <NavLink to="/queue"><Users size={16} />Patient queue</NavLink>
              <NavLink to="/priority"><Gauge size={16} />Priority matrix</NavLink>
              {labAccess && <NavLink to="/lab-results"><FlaskConical size={16} />Upload lab results</NavLink>}
            </>
          : labTech
            ? <>
                <NavLink to="/" end><LayoutDashboard size={16} />Overview</NavLink>
                <NavLink to="/lab-results"><FlaskConical size={16} />Upload lab results</NavLink>
              </>
            : <>
                <NavLink to="/" end onClick={() => {
                  if (location.pathname === '/') {
                    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
                    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
                  }
                }}><HeartPulse size={16} />Home</NavLink>
                <NavLink to="/book"><CalendarDays size={16} />Schedule appointment</NavLink>
                <NavLink to="/priority"><Gauge size={16} />How priority works</NavLink>
              </>}
      </nav>
      <nav className="patient-banner-login" aria-label="Account navigation">
        <span className="patient-banner-user">{patient ? `Patient ${user.id}` : roleLabel}</span>
        <button className="patient-banner-switch-user" type="button" onClick={switchAccount}><LogOut size={15} />Switch user</button>
      </nav>
    </header>
    <main className="main-area">
      <div className="page-content"><ScrollReveal key={location.pathname}><Routes>
        <Route path="/" element={clinician ? <Dashboard /> : labTech ? <LabResultsPage overview /> : <PatientHome patientId={user.id} />} />
        <Route path="/login" element={<LoginPage onLogin={setSession} />} />
        <Route path="/queue" element={clinician ? <QueuePage /> : <Navigate to="/" replace />} />
        <Route path="/lab-results" element={labAccess ? <LabResultsPage /> : patient ? <PatientLabResultsPage /> : <Navigate to="/queue" replace />} />
        <Route path="/book" element={!clinician && !labTech ? <BookingPage /> : <Navigate to="/" replace />} />
        <Route path="/schedule" element={patient ? <ReschedulePage /> : <Navigate to="/" replace />} />
        <Route path="/priority" element={<PriorityPage />} />
        <Route path="/intake" element={!clinician && !labTech ? <IntakePage /> : <Navigate to="/" replace />} />
        <Route path="/billing" element={patient ? <BillingPage patientId={user.id} /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes></ScrollReveal></div>
    </main>
    <footer className="app-demo-notice"><ShieldCheck size={15} aria-hidden="true" /><span>Synthetic demo data only. Do not enter real patient information.</span></footer>
  </div>
}

export default App
