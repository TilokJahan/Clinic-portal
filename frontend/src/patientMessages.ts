export interface PatientMessage {
  id: string
  patientId: number
  patientLabel: string
  message: string
  sentAt: string
}

export const PATIENT_MESSAGES_STORAGE_KEY = 'clinic-portal.patient-messages'

export function loadPatientMessages(): PatientMessage[] {
  let stored: string | null
  try {
    stored = localStorage.getItem(PATIENT_MESSAGES_STORAGE_KEY)
  } catch {
    throw new Error('This browser blocked access to patient messages.')
  }
  if (!stored) return []

  try {
    const value: unknown = JSON.parse(stored)
    if (!Array.isArray(value) || !value.every((item) =>
      item && typeof item.id === 'string' &&
      typeof item.patientId === 'number' &&
      typeof item.patientLabel === 'string' &&
      typeof item.message === 'string' &&
      typeof item.sentAt === 'string')) {
      throw new Error()
    }
    return value as PatientMessage[]
  } catch {
    throw new Error('Saved patient messages could not be read. Clear this browser’s site data to reset the prototype.')
  }
}

export function addPatientMessage(patientId: number, message: string): PatientMessage[] {
  const text = message.trim()
  if (!text) throw new Error('Enter a message before sending.')
  if (text.length > 2000) throw new Error('Messages must be 2,000 characters or fewer.')

  const messages = loadPatientMessages()
  const next = [{
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    patientId,
    patientLabel: `Patient ${String(patientId).padStart(4, '0')}`,
    message: text,
    sentAt: new Date().toISOString(),
  }, ...messages]

  try {
    localStorage.setItem(PATIENT_MESSAGES_STORAGE_KEY, JSON.stringify(next))
  } catch {
    throw new Error('Your message could not be saved in this browser. Check available browser storage and try again.')
  }
  return next
}

export function messagesForPatientLabel(messages: PatientMessage[], patientLabel: string): PatientMessage[] {
  const normalizedLabel = patientLabel.toLowerCase().replace(/[^a-z0-9]/g, '')
  const patientNumber = patientLabel.match(/^patient\s+0*(\d+)$/i)?.[1]
  return messages.filter((message) =>
    (patientNumber !== undefined && String(message.patientId) === patientNumber) ||
    message.patientLabel.toLowerCase().replace(/[^a-z0-9]/g, '') === normalizedLabel)
}
