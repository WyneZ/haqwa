/**
 * C3 Web API shapes (docs/contracts.md, LOCKED 2026-09-28).
 *
 * Hand-written for now. When the FastAPI app exists, these are generated from its
 * OpenAPI schema (decision 2026-09-29) and this file is replaced.
 */

export type Scalar = string | number | boolean

export interface TimelineEvent {
  event: string
  data: Record<string, Scalar>
}

export interface Condition {
  field: string
  op: 'eq' | 'ne' | 'in'
  value: Scalar | Scalar[]
}

export type RuleException = { reset_after: string } | { allow_if: Condition }

export interface ConfirmedExample {
  timeline: TimelineEvent[]
  violation: boolean
}

export type Pattern = 'at_most_once' | 'never_after' | 'must_precede' | 'within_time'

/** C1 rule. Pattern-specific fields are optional here; `pattern` says which are set. */
export interface Rule {
  id: string
  source: string
  pattern: Pattern
  per: string
  event: string
  after?: string
  requires?: string
  start?: string
  within?: string // ISO 8601 duration, e.g. "PT24H" or "P1D"
  except: RuleException[]
  confirmed_examples: ConfirmedExample[]
}

export interface Question {
  id: string // "d1", "d2" … decisions; "c1", "c2" … confirmations
  kind: 'decision' | 'confirmation'
  text: string
  timeline: TimelineEvent[]
  if_yes?: RuleException // decision only
  expected_violation?: boolean // confirmation only
}

export type ClarifyResult =
  | { source: string; status: 'supported'; rule: Rule; questions: Question[] }
  | { source: string; status: 'unsupported'; reason: string }

export interface ClarifyResponse {
  cached: boolean
  results: ClarifyResult[]
}

export interface Answer {
  question: Question
  allowed: boolean
}

export interface AnswersResponse {
  rule: Rule
  mismatches: string[]
}

/** RFC 9457 problem details + stable `code` (C3 errors). */
export interface ApiProblem {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
}
