import type { LogEvent } from '../api/types'

export const FILE_ERROR = 'Please choose a JSON file with a list of events (max 5 MB).'
const MAX_FILE_BYTES = 5_000_000

function parseEvents(text: string): LogEvent[] {
  try {
    const parsed: unknown = JSON.parse(text)
    if (Array.isArray(parsed)) return parsed as LogEvent[]
  } catch {
    // Use the same helpful message for invalid JSON and the wrong top-level shape.
  }
  throw new Error(FILE_ERROR)
}

export async function readEventsFile(file: File): Promise<LogEvent[]> {
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(FILE_ERROR)
  }
  return parseEvents(await file.text())
}

export async function readHrSample(): Promise<LogEvent[]> {
  const response = await fetch('/samples/hr-events.json')
  if (!response.ok) throw new Error('Could not load the HR sample. Please try again.')
  return parseEvents(await response.text())
}
