import type { SuggestedEvent, TraceSummary, TraceVocabulary } from '../api/types'

export type Source =
  | { kind: 'shop' }
  | { kind: 'trace'; name: string; summary: TraceSummary; extraEvents: string[] }
  | { kind: 'live'; vocabulary: TraceVocabulary; suggestedEvents?: SuggestedEvent[] }

export const HR_NAME = 'HR leave sample'
export const HR_RULES = [
  'Decide every leave request within 48 hours.',
  'Never approve leave after it has been cancelled.',
  'Approve the timesheet before paying salary for that employee and period.',
  'Run payroll at most once per employee and period.',
  'The approver must be a different person from the requester.',
].join('\n')
