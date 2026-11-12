export const LAB_FILE_ACCEPT = 'application/pdf,image/png,image/jpeg'
export const MAX_LAB_FILE_BYTES = 10 * 1024 * 1024

export function labFileError(file: File): string | null {
  if (!LAB_FILE_ACCEPT.split(',').includes(file.type)) return 'Choose a PDF, PNG or JPEG file.'
  if (file.size === 0) return 'The file is empty. Choose a report with content.'
  if (file.size > MAX_LAB_FILE_BYTES) return 'The file is over 10 MB.'
  return null
}
