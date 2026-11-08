export type BillStatus = 'paid' | 'due' | 'overdue'

export interface PatientBill {
  id: string
  patient_id: number
  description: string
  service_date: string
  amount_cents: number
  status: BillStatus
  due_date: string | null
}

export type BillingApiResult<T> = { ok: true; data: T } | { ok: false; detail: string }

const MOCK_BILLS: PatientBill[] = [
  { id: 'BILL-1001', patient_id: 1, description: 'Primary care visit', service_date: '2026-10-12', amount_cents: 8500, status: 'due', due_date: '2026-11-12' },
  { id: 'BILL-1002', patient_id: 1, description: 'Laboratory services', service_date: '2026-09-28', amount_cents: 3250, status: 'paid', due_date: null },
  { id: 'BILL-2001', patient_id: 2, description: 'Primary care visit', service_date: '2026-10-18', amount_cents: 7200, status: 'overdue', due_date: '2026-11-01' },
  { id: 'BILL-2002', patient_id: 2, description: 'Laboratory services', service_date: '2026-10-18', amount_cents: 4100, status: 'due', due_date: '2026-11-18' },
  { id: 'BILL-3001', patient_id: 3, description: 'Specialist consultation', service_date: '2026-10-21', amount_cents: 12500, status: 'due', due_date: '2026-11-21' },
]

// Mock contract for the backend endpoint: GET /api/patients/{patient_id}/bills
export const billingApi = {
  async getPatientBills(patientId: number): Promise<BillingApiResult<PatientBill[]>> {
    await new Promise((resolve) => setTimeout(resolve, 180))
    if (!Number.isInteger(patientId) || patientId < 1) {
      return { ok: false, detail: 'A valid patient ID is required.' }
    }
    return {
      ok: true,
      data: MOCK_BILLS
        .filter((bill) => bill.patient_id === patientId)
        .map((bill) => ({ ...bill }))
        .sort((a, b) => b.service_date.localeCompare(a.service_date)),
    }
  },
}
