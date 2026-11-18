import { useEffect, useState } from 'react'
import { Check, Loader2, UserCog } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner } from '../components'
import type { AdminUser, Provider, Role } from '../types'

const ROLE_LABEL: Record<Role, string> = {
  patient: 'Patient', clinician: 'Clinician', physician: 'Physician (doctor)', lab_tech: 'Lab technician', admin: 'Admin',
}
const ROLES = Object.keys(ROLE_LABEL) as Role[]

/** Admin: every account and its role; a physician is linked to the schedule they see. */
export function AdminPage({ selfId }: { selfId: number }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    api.adminUsers().then((r) => { if (r.ok) setUsers(r.data); else setError(r.detail) })
    api.providers().then((r) => { if (r.ok) setProviders(r.data) })
  }, [])
  const count = (role: Role) => users?.filter((u) => u.role === role).length ?? 0

  return <>
    <div className="welcome-row"><div><div className="eyebrow">ADMIN</div><h1>Users and roles</h1>
      <p>Change what each person can do. A role change takes effect the next time they sign in.</p></div></div>
    <section className="role-summary">{ROLES.map((r) => <div key={r} className="panel"><b>{count(r)}</b><span>{ROLE_LABEL[r]}</span></div>)}</section>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {users === null && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading users…</div>}
    {users && <div className="panel admin-table">
      <div className="admin-row admin-head"><span>ACCOUNT</span><span>ROLE</span><span>SCHEDULE (PHYSICIANS)</span><span /></div>
      {users.map((u) => <UserRow key={u.id} user={u} providers={providers} self={u.id === selfId} onSaved={(saved) => setUsers((all) => all?.map((x) => x.id === saved.id ? saved : x) ?? all)} />)}
    </div>}
  </>
}

function UserRow({ user, providers, self, onSaved }: { user: AdminUser; providers: Provider[]; self: boolean; onSaved: (u: AdminUser) => void }) {
  const [role, setRole] = useState<Role>(user.role)
  const [provider, setProvider] = useState<number | null>(user.provider_id)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const changed = role !== user.role || (role === 'physician' && provider !== user.provider_id)

  async function save() {
    setBusy(true); setError(''); setSaved(false)
    const r = await api.updateUser(user.id, role, role === 'physician' ? provider : null)
    setBusy(false)
    if (r.ok) { onSaved(r.data); setSaved(true) } else setError(r.detail)
  }

  return <div className="admin-row">
    <span className="admin-account"><UserCog size={15} /> {user.email}{self && <small> (you)</small>}</span>
    <select aria-label={`Role for ${user.email}`} value={role} disabled={self} onChange={(e) => { setRole(e.target.value as Role); setSaved(false) }}>
      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
    </select>
    {role === 'physician'
      ? <select aria-label={`Schedule for ${user.email}`} value={provider ?? ''} onChange={(e) => { setProvider(e.target.value ? Number(e.target.value) : null); setSaved(false) }}>
          <option value="">Choose a schedule…</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.specialty}</option>)}
        </select>
      : <span className="field-hint">—</span>}
    <span className="admin-actions">
      {changed && <button type="button" className="button button-primary" disabled={busy || (role === 'physician' && !provider)} onClick={save}>
        {busy ? <Loader2 className="spin" size={14} /> : null}Save</button>}
      {saved && !changed && <span className="saved-message"><Check size={14} /> Saved</span>}
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </span>
  </div>
}
