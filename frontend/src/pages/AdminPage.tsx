import { useCallback, useEffect, useState } from 'react'
import { Ban, Check, Copy, Loader2, Mail, Send, ShieldCheck, UserCog, UserPlus } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner } from '../components'
import { formatDateTime } from '../format'
import type { AdminUser, Invitation, Provider, Role } from '../types'

export const ROLE_LABEL: Record<Role, string> = {
  patient: 'Patient', clinician: 'Clinician', physician: 'Physician (doctor)', lab_tech: 'Lab technician', admin: 'Admin',
}
const ROLES = Object.keys(ROLE_LABEL) as Role[]

/** What each role may do (enforced by the backend, app/auth.py). */
const PRIVILEGES: { label: string; roles: Role[] }[] = [
  { label: 'Book visits, describe symptoms, upload own results', roles: ['patient'] },
  { label: 'See symptoms, triage and lab results', roles: ['clinician', 'physician', 'admin'] },
  { label: 'Approve bookings and propose times (live queue)', roles: ['clinician', 'admin'] },
  { label: 'Request tests from the lab', roles: ['clinician', 'physician', 'admin'] },
  { label: 'Own schedule; complete visits with a summary', roles: ['physician', 'admin'] },
  { label: 'Lab requests: propose lab times, upload results', roles: ['lab_tech', 'admin'] },
  { label: 'Invite people, change roles, disable accounts', roles: ['admin'] },
]

/** Admin: invite people by email with a role, and manage every account's role and access. */
export function AdminPage({ selfId }: { selfId: number }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [invites, setInvites] = useState<Invitation[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [error, setError] = useState('')
  const load = useCallback(() => {
    api.adminUsers().then((r) => { if (r.ok) setUsers(r.data); else setError(r.detail) })
    api.invitations().then((r) => { if (r.ok) setInvites(r.data) })
  }, [])
  useEffect(() => {
    load()
    api.providers().then((r) => { if (r.ok) setProviders(r.data) })
  }, [load])
  const count = (role: Role) => users?.filter((u) => u.role === role && u.active !== false).length ?? 0

  return <>
    <div className="welcome-row"><div><div className="eyebrow">ADMIN</div><h1>Users and roles</h1>
      <p>Invite people with a role, change what each person can do, or disable an account. Changes apply at once.</p></div></div>
    <section className="role-summary">{ROLES.map((r) => <div key={r} className="panel"><b>{count(r)}</b><span>{ROLE_LABEL[r]}</span></div>)}</section>
    <InviteForm providers={providers} onSent={load} />
    {invites.length > 0 && <InvitationList invites={invites} onChanged={load} />}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <h2 className="section-title">Accounts</h2>
    {users === null && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading users…</div>}
    {users && <div className="panel admin-table">
      <div className="admin-row admin-head"><span>ACCOUNT</span><span>ROLE</span><span>SCHEDULE (PHYSICIANS)</span><span>ACCESS</span></div>
      {users.map((u) => <UserRow key={u.id} user={u} providers={providers} self={u.id === selfId} onSaved={(saved) => setUsers((all) => all?.map((x) => x.id === saved.id ? saved : x) ?? all)} />)}
    </div>}
    <h2 className="section-title">What each role can do</h2>
    <div className="panel privileges">
      <div className="privilege-row privilege-head"><span /> {ROLES.map((r) => <span key={r}>{ROLE_LABEL[r].replace(' (doctor)', '')}</span>)}</div>
      {PRIVILEGES.map((p) => <div className="privilege-row" key={p.label}><span>{p.label}</span>
        {ROLES.map((r) => <span key={r} aria-label={p.roles.includes(r) ? 'yes' : 'no'}>{p.roles.includes(r) ? <Check size={15} /> : '—'}</span>)}</div>)}
    </div>
  </>
}

function inviteText(invite: Invitation, link: string) {
  const role = ROLE_LABEL[invite.role].toLowerCase()
  return {
    subject: 'Your invitation to Cloud Clinic',
    body: `Hello,\n\nYou're invited to join the Cloud Clinic portal as ${/^[aeiou]/.test(role) ? 'an' : 'a'} ${role}${invite.provider_name ? ` (${invite.provider_name}'s schedule)` : ''}.\n\nOpen this link to create your account (it works once, until ${formatDateTime(invite.expires_at)}):\n${link}\n\nCloud Clinic`,
  }
}

function InviteForm({ providers, onSent }: { providers: Provider[]; onSent: () => void }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('clinician')
  const [provider, setProvider] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState<Invitation | null>(null)

  async function send(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(''); setSent(null)
    const r = await api.invite(email, role, role === 'physician' ? provider : null)
    setBusy(false)
    if (r.ok) { setSent(r.data); setEmail(''); onSent() } else setError(r.detail)
  }

  return <form className="panel invite-form" onSubmit={send}>
    <div className="lab-card-head"><div className="info-icon mint"><UserPlus /></div><div><h3>Invite someone</h3>
      <p>They get a personal link to create their account with this role. It works once, for 7 days.</p></div></div>
    <div className="invite-fields">
      <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" /></label>
      <label>Role<select value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></label>
      {role === 'physician' && <label>Schedule<select required value={provider ?? ''} onChange={(e) => setProvider(e.target.value ? Number(e.target.value) : null)}>
        <option value="">Choose a schedule…</option>{providers.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.specialty}</option>)}</select></label>}
      <button className="button button-primary" disabled={busy || !email || (role === 'physician' && !provider)}>
        {busy ? <Loader2 className="spin" size={16} /> : <Send size={16} />} Create invitation</button>
    </div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {sent?.link && <InviteLink invite={sent} />}
  </form>
}

function InviteLink({ invite }: { invite: Invitation }) {
  const link = `${window.location.origin}${invite.link}`
  const [copied, setCopied] = useState(false)
  const { subject, body } = inviteText(invite, link)
  const mailto = `mailto:${encodeURIComponent(invite.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  return <div className="invite-link">
    <p><Check size={14} /> Invitation ready for <b>{invite.email}</b> as {ROLE_LABEL[invite.role].toLowerCase()}. Send them this link:</p>
    <code>{link}</code>
    <div className="request-actions">
      <a className="button button-primary" href={mailto}><Mail size={16} /> Email it</a>
      <button type="button" className="button button-secondary" onClick={() => { void navigator.clipboard?.writeText(link); setCopied(true) }}>
        {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? 'Copied' : 'Copy link'}</button>
    </div>
    <span className="field-hint">“Email it” opens a ready-to-send message in your own email app.</span>
  </div>
}

function InvitationList({ invites, onChanged }: { invites: Invitation[]; onChanged: () => void }) {
  const [error, setError] = useState('')
  const [shown, setShown] = useState<number | null>(null)
  async function revoke(id: number) {
    setError('')
    const r = await api.revokeInvitation(id)
    if (r.ok) onChanged(); else setError(r.detail)
  }
  return <div className="panel admin-table invitations">
    <div className="admin-row admin-head"><span>INVITED</span><span>ROLE</span><span>STATUS</span><span /></div>
    {invites.map((i) => <div key={i.id}>
      <div className="admin-row">
        <span className="admin-account"><Mail size={15} /> {i.email}</span>
        <span>{ROLE_LABEL[i.role]}{i.provider_name ? ` · ${i.provider_name}` : ''}</span>
        <span><span className={`request-state ${i.status === 'pending' ? 'proposed' : i.status === 'accepted' ? 'completed' : 'cancelled'}`}>{i.status}</span>
          {i.status === 'pending' && <small className="field-hint"> until {formatDateTime(i.expires_at)}</small>}</span>
        <span className="admin-actions">{i.status === 'pending' && <>
          <button type="button" className="text-button" onClick={() => setShown(shown === i.id ? null : i.id)}>Link</button>
          <button type="button" className="text-button" onClick={() => revoke(i.id)}>Revoke</button></>}</span>
      </div>
      {shown === i.id && i.link && <InviteLink invite={i} />}
    </div>)}
    {error && <ErrorBanner>{error}</ErrorBanner>}
  </div>
}

function UserRow({ user, providers, self, onSaved }: { user: AdminUser; providers: Provider[]; self: boolean; onSaved: (u: AdminUser) => void }) {
  const [role, setRole] = useState<Role>(user.role)
  const [provider, setProvider] = useState<number | null>(user.provider_id)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const active = user.active !== false
  const changed = role !== user.role || (role === 'physician' && provider !== user.provider_id)

  async function save(nextActive?: boolean) {
    setBusy(true); setError(''); setSaved(false)
    const r = await api.updateUser(user.id, role, role === 'physician' ? provider : null, nextActive)
    setBusy(false)
    if (r.ok) { onSaved(r.data); setSaved(true) } else setError(r.detail)
  }

  return <div className={`admin-row ${active ? '' : 'disabled-user'}`}>
    <span className="admin-account"><UserCog size={15} /> {user.email}{self && <small> (you)</small>}{!active && <small className="request-state cancelled">disabled</small>}</span>
    <select aria-label={`Role for ${user.email}`} value={role} disabled={self} onChange={(e) => { setRole(e.target.value as Role); setSaved(false) }}>
      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
    </select>
    {role === 'physician'
      ? <select aria-label={`Schedule for ${user.email}`} value={provider ?? ''} disabled={self} onChange={(e) => { setProvider(e.target.value ? Number(e.target.value) : null); setSaved(false) }}>
          <option value="">Choose a schedule…</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.specialty}</option>)}
        </select>
      : <span className="field-hint">—</span>}
    <span className="admin-actions">
      {changed && <button type="button" className="button button-primary" disabled={busy || (role === 'physician' && !provider)} onClick={() => save()}>
        {busy ? <Loader2 className="spin" size={14} /> : null}Save</button>}
      {!changed && !self && <button type="button" className="text-button" disabled={busy} onClick={() => save(!active)}>
        {active ? <><Ban size={14} /> Disable</> : <><ShieldCheck size={14} /> Enable</>}</button>}
      {saved && !changed && <span className="saved-message"><Check size={14} /> Saved</span>}
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </span>
  </div>
}
