import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, HeartPulse, ShieldCheck } from 'lucide-react'
import { DEMO_ACCOUNTS, type Role, type Session } from '../session'

export function LoginPage({ onLogin }: { onLogin: (session: Session) => void }) {
  const navigate = useNavigate()
  const [role, setRole] = useState<Role>('patient')
  const accounts = DEMO_ACCOUNTS.filter((a) => a.role === role)
  const [userId, setUserId] = useState(accounts[0].userId)

  function chooseRole(next: Role) {
    setRole(next)
    setUserId(DEMO_ACCOUNTS.find((a) => a.role === next)!.userId)
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    onLogin(DEMO_ACCOUNTS.find((a) => a.userId === userId)!)
    navigate(role === 'clinician' ? '/queue' : '/')
  }

  return <div className="login-wrap"><form className="panel login-card" onSubmit={submit}>
    <div className="login-brand"><div className="brand-mark"><HeartPulse size={20} /></div><span>Cloud Clinic</span></div>
    <div className="eyebrow">WELCOME TO CLOUD CLINIC</div>
    <h1>Good to see you.</h1>
    <p>Choose a demo account to continue.</p>
    <div className="login-role"><span>Continue as</span><div>
      <button type="button" className={role === 'patient' ? 'selected' : ''} onClick={() => chooseRole('patient')}>Patient</button>
      <button type="button" className={role === 'clinician' ? 'selected' : ''} onClick={() => chooseRole('clinician')}>Clinician</button>
    </div></div>
    <label>Demo account
      <select value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
        {accounts.map((a) => <option key={a.userId} value={a.userId}>{a.email}</option>)}
      </select>
    </label>
    <button className="button button-primary login-submit" type="submit">Continue <ArrowRight size={16} /></button>
    <div className="login-foot"><ShieldCheck size={14} /> Synthetic demo accounts only</div>
    <p className="login-demo">Prototype sign-in: no password is asked for and nothing is sent. Real sign-in comes with auth.</p>
  </form></div>
}
