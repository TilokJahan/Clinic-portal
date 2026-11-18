import type { ExamType, LabNeed } from './types'

/** Every kind of test the portal handles (app/lab_needs.py on the backend). */
export const EXAM_LABELS: Record<ExamType, string> = {
  blood: 'Blood test',
  urine: 'Urine test',
  ultrasound: 'Ultrasound',
  xray: 'X-ray',
  ct: 'CT scan',
  mri: 'MRI',
  ecg: 'ECG (heart tracing)',
  other: 'Other test',
}
export const EXAM_TYPES = Object.keys(EXAM_LABELS) as ExamType[]

/** A result older than this no longer counts for a new visit. */
export const RECENT_DAYS = 40

export const NEED_LABEL: Record<LabNeed['status'], string> = {
  recent: 'Recent result on file',
  outdated: 'Only an older result (over 40 days)',
  missing: 'No result yet',
  requested: 'Requested from the lab',
}

/** Days between a YYYY-MM-DD date and today. */
export function daysAgo(isoDate: string, now = new Date()): number {
  const [y, m, d] = isoDate.split('-').map(Number)
  const then = new Date(y, m - 1, d)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((today.getTime() - then.getTime()) / 86_400_000)
}
