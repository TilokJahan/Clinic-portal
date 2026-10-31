import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, HeartPulse, Loader2, ShieldCheck } from 'lucide-react'
import { authMode, DEMO_ACCOUNTS, demoLogin, passwordLogin, signUp, type Session } from '../auth'
import { ErrorBanner } from '../components'
import type { Role } from '../types'

export function LoginPage({ onLogin }: { onLogin: (session: Session) => void }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function finish(result: Awaited<ReturnType<typeof demoLogin>>) {
    setBusy(false)
    if (!result.ok) { setError(result.detail); return }
    onLogin(result.data)
    navigate(result.data.user.role === 'patient' ? '/' : '/queue')
  }

  return <div className="login-wrap"><div className="panel login-card">
    <div className="login-brand"><div className="brand-mark"><HeartPulse size={20} /></div><span>Cloud Clinic</span></div>
    <div className="eyebrow">WELCOME TO CLOUD CLINIC</div>
    <h1>Good to see you.</h1>
    {authMode === 'identity-platform'
      ? <PasswordForm busy={busy} onSubmit={async (email, password, creating) => {
          setBusy(true); setError(''); setNotice('')
          if (!creating) return finish(await passwordLogin(email, password))
          const result = await signUp(email, password)
          setBusy(false)
          if (result.ok) setNotice('Account created. Check your email for a verification link, then sign in.')
          else setError(result.detail)
        }} />
      : <DemoForm busy={busy} onSubmit={async (email) => { setBusy(true); setError(''); finish(await demoLogin(email)) }} />}
    {notice && <p className="login-notice" role="status">{notice}</p>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <div className="login-foot"><ShieldCheck size={14} /> {authMode === 'identity-platform' ? 'Secured by Google Identity Platform' : 'Synthetic demo accounts only'}</div>
    {authMode !== 'identity-platform' && <p className="login-demo">Demo sign-in for local development: no password, synthetic data only.</p>}
  </div></div>
}

function DemoForm({ busy, onSubmit }: { busy: boolean; onSubmit: (email: string) => void }) {
  const [role, setRole] = useState<Role>('patient')
  const accounts = DEMO_ACCOUNTS.filter((a) => a.role === role)
  const [email, setEmail] = useState(accounts[0].email)
  const choose = (next: Role) => { setRole(next); setEmail(DEMO_ACCOUNTS.find((a) => a.role === next)!.email) }
  return <form onSubmit={(e) => { e.preventDefault(); onSubmit(email) }}>
    <p>Choose a demo account to continue.</p>
    <div className="login-role"><span>Continue as</span><div>
      <button type="button" className={role === 'patient' ? 'selected' : ''} onClick={() => choose('patient')}>Patient</button>
      <button type="button" className={role === 'clinician' ? 'selected' : ''} onClick={() => choose('clinician')}>Clinician</button>
    </div></div>
    <label>Demo account
      <select value={email} onChange={(e) => setEmail(e.target.value)}>
        {accounts.map((a) => <option key={a.email} value={a.email}>{a.email}</option>)}
      </select>
    </label>
    <button className="button button-primary login-submit" type="submit" disabled={busy}>{busy ? <Loader2 className="spin" size={16} /> : null} Continue <ArrowRight size={16} /></button>
  </form>
}

function PasswordForm({ busy, onSubmit }: { busy: boolean; onSubmit: (email: string, password: string, creating: boolean) => void }) {
  const [creating, setCreating] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  return <form onSubmit={(e) => { e.preventDefault(); onSubmit(email.trim(), password, creating) }}>
    <p>{creating ? 'Create a patient account.' : 'Sign in to continue to your care space.'}</p>
    <label>Email address<input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
    <label>Password<input type="password" autoComplete={creating ? 'new-password' : 'current-password'} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
    <button className="button button-primary login-submit" type="submit" disabled={busy}>{busy ? <Loader2 className="spin" size={16} /> : null} {creating ? 'Create account' : 'Sign in'} <ArrowRight size={16} /></button>
    <button type="button" className="text-button" onClick={() => setCreating(!creating)}>{creating ? 'I already have an account' : 'New patient? Create an account'}</button>
  </form>
}
