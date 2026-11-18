import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, HeartPulse, Loader2, UserPlus } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner } from '../components'
import { formatDateTime } from '../format'
import type { InvitationView } from '../types'
import type { Session } from '../auth'
import { ROLE_LABEL } from './AdminPage'

/** Someone opened an admin's invite link: show who it's for and as what, then register. */
export function InvitePage({ onLogin }: { onLogin: (session: Session) => void }) {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const [invite, setInvite] = useState<InvitationView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.viewInvitation(token).then((r) => { if (r.ok) setInvite(r.data); else setError(r.detail) }) }, [token])

  async function accept() {
    setBusy(true); setError('')
    const r = await api.acceptInvitation(token)
    setBusy(false)
    if (!r.ok) { setError(r.detail); return }
    onLogin({ token: r.data.access_token, user: r.data.user })
    navigate('/')
  }

  return <div className="login-wrap"><div className="panel login-card">
    <div className="login-brand"><div className="brand-mark"><HeartPulse size={20} /></div><span>Cloud Clinic</span></div>
    <div className="eyebrow">INVITATION</div>
    {!invite && !error && <p><Loader2 className="spin" size={16} /> Opening your invitation…</p>}
    {error && !invite && <><h1>This link doesn’t work</h1><ErrorBanner>{error}</ErrorBanner><p>Ask the person who invited you for a new link.</p></>}
    {invite && <>
      <h1>You’re invited</h1>
      <p>Join the Cloud Clinic portal as <b>{ROLE_LABEL[invite.role]}</b>{invite.provider_name ? <>, with <b>{invite.provider_name}</b>’s schedule</> : null}.</p>
      <p className="field-hint">Account: {invite.email}</p>
      {invite.status !== 'pending'
        ? <ErrorBanner>This invitation is {invite.status}. Ask for a new link.</ErrorBanner>
        : invite.method === 'accept'
          ? <button className="button button-primary login-submit" disabled={busy} onClick={accept}>
              {busy ? <Loader2 className="spin" size={16} /> : <UserPlus size={16} />} Create my account <ArrowRight size={16} /></button>
          : <><p>Sign up with <b>{invite.email}</b> on the sign-in page; your role is set at your first sign-in.</p>
              <button className="button button-primary login-submit" onClick={() => navigate('/login')}>Go to sign-up <ArrowRight size={16} /></button></>}
      {invite.status === 'pending' && <p className="field-hint">The link works once, until {formatDateTime(invite.expires_at)}.</p>}
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </>}
  </div></div>
}
