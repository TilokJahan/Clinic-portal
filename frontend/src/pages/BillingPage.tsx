import { useEffect, useState } from 'react'
import { ReceiptText } from 'lucide-react'
import { ErrorBanner } from '../components'
import { billingApi, type PatientBill } from '../billingApi'

function formatCurrency(cents: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(cents / 100)
}

function formatDate(date: string): string {
  return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })
}

export function BillingPage({ patientId }: { patientId: number }) {
  const [bills, setBills] = useState<PatientBill[]>([])
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let active = true
    void billingApi.getPatientBills(patientId).then((result) => {
      if (!active) return
      if (result.ok) setBills(result.data)
      else setError(result.detail)
      setLoaded(true)
    }).catch((reason: unknown) => {
      if (!active) return
      setError(reason instanceof Error ? reason.message : 'Bills could not be loaded.')
      setLoaded(true)
    })
    return () => { active = false }
  }, [patientId])

  const outstanding = bills.filter((bill) => bill.status !== 'paid').reduce((total, bill) => total + bill.amount_cents, 0)

  return <>
    <div className="welcome-row">
      <div>
        <div className="eyebrow"><ReceiptText size={14} /> SAMPLE DATA</div>
        <h1>Billing and statements</h1>
        <p>Sample statements for demonstration only. No real charges or payments.</p>
      </div>
      {loaded && <div className="lab-result-count">{formatCurrency(outstanding)} sample balance</div>}
    </div>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <section className="billing-list" aria-label="Sample bills">
      {!loaded && <div className="panel empty-state">Loading sample bills…</div>}
      {loaded && bills.map((bill) => (
        <article className="panel billing-card" key={bill.id}>
          <div className="billing-card-heading">
            <div className="lab-result-avatar"><ReceiptText size={18} /></div>
            <div><h2>{bill.description}</h2><p>Statement {bill.id} · Service date {formatDate(bill.service_date)}</p></div>
            <span className={`billing-status ${bill.status}`}>{bill.status}</span>
          </div>
          <div className="billing-card-details">
            <span>{bill.due_date ? `Due ${formatDate(bill.due_date)}` : 'No payment due'}</span>
            <b>{formatCurrency(bill.amount_cents)}</b>
          </div>
        </article>
      ))}
      {loaded && !error && bills.length === 0 && <div className="panel empty-state">No sample bills are available for this demo account.</div>}
    </section>
  </>
}
