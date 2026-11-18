import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, HeartPulse, Loader2, ShieldCheck } from 'lucide-react'
import { authMode, DEMO_ACCOUNTS, demoLogin, entraLogin, type Session } from '../auth'
import { ErrorBanner } from '../components'
import type { Role } from '../types'

export function LoginPage({ onLogin }: { onLogin: (session: Session) => void }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function finish(result: Awaited<ReturnType<typeof demoLogin>>) {
    setBusy(false)
    if (!result.ok) { setError(result.detail); return }
    onLogin(result.data)
    // Each role's home page is "/" (admin: users, clinician: overview, physician: schedule, lab: requests)
    navigate(result.data.user.role === 'clinician' ? '/queue' : '/')
  }

  return <div className="login-wrap"><div className="panel login-card">
    <div className="login-brand"><div className="brand-mark"><HeartPulse size={20} /></div><span>Cloud Clinic</span></div>
    <div className="eyebrow">WELCOME TO CLOUD CLINIC</div>
    <h1>Good to see you.</h1>
    {authMode === 'entra'
      ? <EntraButtons busy={busy} onClick={async (creating) => { setBusy(true); setError(''); finish(await entraLogin(creating)) }} />
      : <DemoForm busy={busy} onSubmit={async (email, passcode) => { setBusy(true); setError(''); finish(await demoLogin(email, passcode)) }} />}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <div className="login-foot"><ShieldCheck size={14} /> {authMode === 'entra' ? 'Secured by Microsoft Entra ID' : 'Synthetic demo accounts only'}</div>
    {authMode !== 'entra' && <p className="login-demo">Demo sign-in with synthetic accounts and a shared demo passcode. No real patient data.</p>}
  </div></div>
}

const OTHER = '__other__'

function DemoForm({ busy, onSubmit }: { busy: boolean; onSubmit: (email: string, passcode: string) => void }) {
  const [role, setRole] = useState<Role>('patient')
  const accounts = DEMO_ACCOUNTS.filter((a) => a.role === role)
  const [email, setEmail] = useState(accounts[0].email)
  const [passcode, setPasscode] = useState('')
  const [other, setOther] = useState(false)
  const choose = (next: Role) => { setRole(next); setOther(false); setEmail(DEMO_ACCOUNTS.find((a) => a.role === next)!.email) }
  return <form onSubmit={(e) => { e.preventDefault(); onSubmit(email, passcode) }}>
    <p>Choose a demo account to continue.</p>
    <div className="login-role"><span>Continue as</span><div>
      {([['patient', 'Patient'], ['clinician', 'Clinician'], ['physician', 'Physician'], ['lab_tech', 'Lab tech'], ['admin', 'Admin']] as [Role, string][]).map(([r, label]) =>
        <button type="button" key={r} className={role === r ? 'selected' : ''} onClick={() => choose(r)}>{label}</button>)}
    </div></div>
    <label>Demo account
      <select value={other ? OTHER : email} onChange={(e) => { const v = e.target.value; setOther(v === OTHER); if (v !== OTHER) setEmail(v); else setEmail('') }}>
        {accounts.map((a) => <option key={a.email} value={a.email}>{a.email}</option>)}
        <option value={OTHER}>Another account (invited)…</option>
      </select>
    </label>
    {other && <label>Your email
      <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="The email you were invited with" required />
    </label>}
    {authMode === 'dev' && <label>Demo passcode
      <input type="password" value={passcode} onChange={(e) => setPasscode(e.target.value)} autoComplete="off" placeholder="Ask the team for the passcode" />
    </label>}
    <button className="button button-primary login-submit" type="submit" disabled={busy}>{busy ? <Loader2 className="spin" size={16} /> : null} Continue <ArrowRight size={16} /></button>
  </form>
}

function EntraButtons({ busy, onClick }: { busy: boolean; onClick: (creating: boolean) => void }) {
  return <div>
    <p>Sign in with your email address. New patients can create an account; we'll send a code to verify your email.</p>
    <button className="button button-primary login-submit" type="button" disabled={busy} onClick={() => onClick(false)}>
      {busy ? <Loader2 className="spin" size={16} /> : null} Sign in <ArrowRight size={16} />
    </button>
    <button type="button" className="text-button" disabled={busy} onClick={() => onClick(true)}>New patient? Create an account</button>
  </div>
}
