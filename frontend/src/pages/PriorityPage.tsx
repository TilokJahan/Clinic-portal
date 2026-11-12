import { useEffect, useState } from 'react'
import { FlaskConical, Loader2, MessageSquareText, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { ErrorBanner, UrgencyPill } from '../components'
import type { Urgency, UrgencyMatrix } from '../types'

const ORDER: (Urgency | null)[] = [null, 'routine', 'soon', 'urgent']
const RANK: Record<Urgency, number> = { routine: 0, soon: 1, urgent: 2 }
const higher = (a: Urgency | null, b: Urgency | null) => (!a || !b ? a ?? b : RANK[a] >= RANK[b] ? a : b)

/** The urgency matrix (GET /urgency-matrix): what makes each priority, and how soon it is seen. */
export function PriorityPage() {
  const [matrix, setMatrix] = useState<UrgencyMatrix | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.urgencyMatrix().then((r) => (r.ok ? setMatrix(r.data) : setError(r.detail))) }, [])

  return <>
    <div className="welcome-row"><div><h1>How priority is decided</h1><p>The same rules set the clinician queue order and the times a patient can choose.</p></div></div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {!matrix && !error && <div className="panel empty-state"><Loader2 className="spin" size={18} /> Loading…</div>}
    {matrix && <>
      <section className="panel matrix-panel" aria-labelledby="matrix-levels">
        <h2 id="matrix-levels">Urgency matrix</h2>
        <div className="matrix-table" role="table" aria-label="Urgency matrix">
          <div className="matrix-row matrix-head" role="row">
            <span role="columnheader">Priority</span><span role="columnheader">Be seen</span>
            <span role="columnheader"><MessageSquareText size={14} /> Symptom signals</span>
            <span role="columnheader"><FlaskConical size={14} /> Lab signals</span>
            <span role="columnheader">What happens</span>
          </div>
          {matrix.levels.map((level) => <div className={`matrix-row level-${level.urgency}`} role="row" key={level.urgency}>
            <span role="cell"><UrgencyPill urgency={level.urgency} /></span>
            <span role="cell"><b>{level.seen_within}</b></span>
            <span role="cell"><ul>{level.symptom_signals.map((s) => <li key={s}>{s}</li>)}</ul></span>
            <span role="cell"><ul>{level.lab_signals.map((s) => <li key={s}>{s}</li>)}</ul></span>
            <span role="cell">{level.action}</span>
          </div>)}
        </div>
      </section>
      <section className="panel matrix-panel" aria-labelledby="matrix-grid">
        <h2 id="matrix-grid">Combining symptoms and labs</h2>
        <p className="field-hint">The priority is the higher of the two. Rows are the symptom priority, columns the lab priority.</p>
        <table className="matrix-grid">
          <thead><tr><th scope="col">Symptoms ↓ / Labs →</th>{ORDER.map((lab) => <th scope="col" key={lab ?? 'none'}>{lab ? <UrgencyPill urgency={lab} /> : 'No lab yet'}</th>)}</tr></thead>
          <tbody>{ORDER.map((symptom) => <tr key={symptom ?? 'none'}>
            <th scope="row">{symptom ? <UrgencyPill urgency={symptom} /> : 'No intake yet'}</th>
            {ORDER.map((lab) => {
              const result = higher(symptom, lab)
              return <td key={lab ?? 'none'}>{result ? <UrgencyPill urgency={result} /> : <span className="field-hint">Waiting</span>}</td>
            })}
          </tr>)}</tbody>
        </table>
      </section>
      <section className="panel matrix-panel" aria-labelledby="matrix-rules">
        <h2 id="matrix-rules">Safety rules</h2>
        <ol className="matrix-rules">{matrix.rules.map((r) => <li key={r}>{r}</li>)}</ol>
        <div className="drawer-safety"><ShieldCheck size={16} /> AI suggestions support clinical judgment and are not a diagnosis. In an emergency, call your local emergency number.</div>
      </section>
    </>}
  </>
}
