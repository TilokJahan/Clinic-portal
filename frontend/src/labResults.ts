export interface LabResult {
  id: string
  patientId: string | null
  patientName: string | null
  fileName: string
  uploadedAt: string
  values: Record<string, string>
  fileDataUrl?: string
}

const STORAGE_KEY = 'clinic-portal.lab-results'

function csvRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let value = ''
  let quoted = false
  let quoteClosed = false

  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        value += '"'
        i++
      } else if (char === '"') {
        quoted = false
        quoteClosed = true
      } else {
        value += char
      }
      continue
    }

    if (quoteClosed) {
      if (char === ',') {
        row.push(value)
        value = ''
        quoteClosed = false
      } else if (char === '\n' || char === '\r') {
        row.push(value)
        if (row.some((cell) => cell.trim())) rows.push(row)
        row = []
        value = ''
        quoteClosed = false
        if (char === '\r' && text[i + 1] === '\n') i++
      } else if (char !== ' ' && char !== '\t') {
        throw new Error('The CSV has unexpected text after a quoted value.')
      }
      continue
    }

    if (char === '"') {
      if (value) throw new Error('The CSV has a quote inside an unquoted value.')
      quoted = true
    } else if (char === ',') {
      row.push(value)
      value = ''
    } else if (char === '\n' || char === '\r') {
      row.push(value)
      if (row.some((cell) => cell.trim())) rows.push(row)
      row = []
      value = ''
      if (char === '\r' && text[i + 1] === '\n') i++
    } else {
      value += char
    }
  }

  if (quoted) throw new Error('The CSV has an unclosed quoted value.')
  if (value || row.length || quoteClosed) {
    row.push(value)
    if (row.some((cell) => cell.trim())) rows.push(row)
  }
  return rows
}

function normalizeHeader(value: string): string {
  return value.replace(/^\uFEFF/, '').trim().toLowerCase().replace(/[\s-]+/g, '_')
}

export function parseLabCsv(
  text: string,
  fileName: string,
  uploadedAt = new Date().toISOString(),
  patient?: { id: number; name: string },
): LabResult[] {
  const rows = csvRows(text)
  const headers = rows.shift()?.map((header) => header.replace(/^\uFEFF/, '').trim())
  if (!headers?.length) throw new Error('The CSV is empty or has no header row.')
  if (headers.some((header) => !header)) throw new Error('Every CSV column needs a header.')

  const normalized = headers.map(normalizeHeader)
  if (new Set(normalized).size !== normalized.length) throw new Error('The CSV has duplicate column headers.')

  const idIndex = normalized.findIndex((header) => ['patient_id', 'patientid', 'id', 'mrn'].includes(header))
  const nameIndex = normalized.findIndex((header) => ['patient_name', 'patientname', 'name'].includes(header))
  if (!patient && idIndex < 0 && nameIndex < 0) {
    throw new Error('Add a patient_id, patient_name, or name column so results can be matched to a patient.')
  }

  const resultHeaders = headers.filter((_, index) => index !== idIndex && index !== nameIndex)
  if (!resultHeaders.length) throw new Error('Add at least one lab-result column besides the patient identifier.')

  const dataRows = rows.map((cells, index) => {
    if (cells.length > headers.length) throw new Error(`CSV row ${index + 2} has more values than the header.`)
    const padded = [...cells, ...Array(Math.max(0, headers.length - cells.length)).fill('')]
    const patientId = patient ? String(patient.id) : idIndex < 0 ? '' : padded[idIndex].trim()
    const patientName = patient ? patient.name : nameIndex < 0 ? '' : padded[nameIndex].trim()
    if (!patientId && !patientName) throw new Error(`CSV row ${index + 2} is missing a patient name or ID.`)

    const values: Record<string, string> = {}
    headers.forEach((header, column) => {
      if (column !== idIndex && column !== nameIndex) values[header] = padded[column].trim()
    })
    return {
      id: `${uploadedAt}-${index}-${Math.random().toString(36).slice(2, 8)}`,
      patientId: patientId || null,
      patientName: patientName || null,
      fileName,
      uploadedAt,
      values,
    }
  })

  if (!dataRows.length) throw new Error('The CSV has headers but no lab-result rows.')
  return dataRows
}

export function loadLabResults(): LabResult[] {
  let stored: string | null
  try {
    stored = localStorage.getItem(STORAGE_KEY)
  } catch {
    throw new Error('This browser blocked access to saved lab results.')
  }
  if (!stored) return []

  try {
    const value: unknown = JSON.parse(stored)
    if (!Array.isArray(value) || !value.every((item) =>
      item && typeof item.id === 'string' &&
      (typeof item.patientId === 'string' || item.patientId === null) &&
      (typeof item.patientName === 'string' || item.patientName === null) &&
      typeof item.fileName === 'string' && typeof item.uploadedAt === 'string' &&
      (item.fileDataUrl === undefined || typeof item.fileDataUrl === 'string') &&
      item.values && typeof item.values === 'object' && !Array.isArray(item.values))) {
      throw new Error()
    }
    return value as LabResult[]
  } catch {
    throw new Error('Saved lab results could not be read. Clear this browser’s site data to reset the prototype.')
  }
}

export function saveLabResults(results: LabResult[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(results))
  } catch {
    throw new Error('Lab results could not be saved in this browser. Check available browser storage and try again.')
  }
}

function normalizePatientName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '')
}

export function labResultsForPatient(results: LabResult[], patientId: number, patientEmail: string): LabResult[] {
  const patientNumber = String(patientId)
  const emailName = patientEmail.split('@')[0]
  const patientNames = new Set([
    normalizePatientName(emailName),
    normalizePatientName(`patient${patientId}`),
    normalizePatientName(`Patient ${String(patientId).padStart(4, '0')}`),
  ])
  return results.filter((result) =>
    result.patientId === patientNumber ||
    (result.patientName !== null && patientNames.has(normalizePatientName(result.patientName))))
}

export function labResultsForPatientLabel(results: LabResult[], patientLabel: string): LabResult[] {
  const patientNumber = patientLabel.match(/^patient\s+0*(\d+)$/i)?.[1]
  const patientNames = new Set([normalizePatientName(patientLabel)])
  if (patientNumber) patientNames.add(normalizePatientName(`patient${patientNumber}`))

  return results.filter((result) =>
    (patientNumber !== undefined && result.patientId !== null && result.patientId.replace(/^0+(?=\d)/, '') === patientNumber) ||
    (result.patientName !== null && patientNames.has(normalizePatientName(result.patientName))))
}
