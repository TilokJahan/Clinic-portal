import { useState } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { CalendarDays, CircleHelp, HeartPulse, LayoutDashboard, LogOut, Menu, Plus, Users, X } from 'lucide-react'
import { apiMode } from './api'
import { BookingPage } from './pages/BookingPage'
import { Dashboard } from './pages/Dashboard'
import { IntakePage } from './pages/IntakePage'
import { LoginPage } from './pages/LoginPage'
import { PatientHome } from './pages/PatientHome'
import { QueuePage } from './pages/QueuePage'
import { useSession } from './session'

const PAGE_NAMES: Record<string, string> = { '/queue': 'Patient queue', '/book': 'Appointments', '/intake': 'Symptom intake', '/login': 'Sign in' }

function App() {
  const { session, setSession, signOut } = useSession()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  if (!session) return <Routes><Route path="/login" element={<LoginPage onLogin={setSession} />} /><Route path="*" element={<Navigate to="/login" replace />} /></Routes>

  const { user } = session
  const clinician = user.role !== 'patient'
  const switchAccount = () => { signOut(); navigate('/login') }
  const close = () => setMobileOpen(false)

  return <div className="app-shell">
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><HeartPulse size={20} strokeWidth={2.4} /></div><div><b>Cloud</b><span>CLINIC PORTAL</span></div><button className="icon-button close-menu" onClick={close} aria-label="Close navigation"><X size={18} /></button></div>
      <div className="clinic-switch"><div className="clinic-avatar">C</div><div><b>Cloud Clinic</b><span>Primary care</span></div></div>
      <div className="nav-label">WORKSPACE</div>
      {clinician
        ? <nav className="nav-list" onClick={close}><NavLink to="/" end><LayoutDashboard size={18} />Overview</NavLink><NavLink to="/queue"><Users size={18} />Patient queue</NavLink></nav>
        : <nav className="nav-list" onClick={close}><NavLink to="/" end><HeartPulse size={18} />Home</NavLink><NavLink to="/book"><CalendarDays size={18} />Book a visit</NavLink><NavLink to="/intake"><Plus size={18} />Symptom intake</NavLink></nav>}
      <div className="sidebar-bottom">
        <div className="help-card"><div className="help-icon"><CircleHelp size={17} /></div><b>Synthetic data only</b><p>{apiMode === 'mock' ? 'Using the mock API (no backend).' : 'Connected to the clinic API.'} Never enter real patient information.</p></div>
        <div className="profile"><div className="profile-avatar">{clinician ? 'DR' : `P${user.id}`}</div><div><b>{user.email}</b><span>{clinician ? 'Clinician' : 'Patient'}</span></div>
          <button className="icon-button" onClick={switchAccount} aria-label="Switch account" title="Switch account"><LogOut size={16} /></button></div>
      </div>
    </aside>
    {mobileOpen && <button className="scrim" onClick={close} aria-label="Close menu" />}
    <main className="main-area">
      <header className="topbar"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
        <div className="breadcrumbs">Workspace <span>/</span> <b>{PAGE_NAMES[location.pathname] ?? 'Overview'}</b></div>
        <div className="top-actions"><span className="role-chip">{clinician ? 'Clinician' : 'Patient'}</span><button className="button button-secondary switch-button" onClick={switchAccount}>Switch account</button></div>
      </header>
      <div className="page-content"><Routes>
        <Route path="/" element={clinician ? <Dashboard /> : <PatientHome />} />
        <Route path="/login" element={<LoginPage onLogin={setSession} />} />
        <Route path="/queue" element={clinician ? <QueuePage /> : <Navigate to="/" replace />} />
        <Route path="/book" element={clinician ? <Navigate to="/" replace /> : <BookingPage />} />
        <Route path="/intake" element={clinician ? <Navigate to="/" replace /> : <IntakePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes></div>
    </main>
  </div>
}

export default App
