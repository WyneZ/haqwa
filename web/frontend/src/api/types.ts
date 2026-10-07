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
  /** Offset from the first event, ISO 8601 duration (e.g. "P1DT1H"). Set by core for time rules. */
  at?: string
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

/** C1 spec: what screen 1 hands to screen 2. */
export interface Spec {
  version: 1
  rules: Rule[]
}

/** C3 endpoint 4: one demo scenario (Track B `demo.list_scenarios()`). */
export interface Scenario {
  id: string
  title: string
  fault: string
  agent: 'naive' | 'fixed'
  description: string
  expected: 'violation' | 'pass'
}

/** C2 event: what the agent did, in rule names. `ts` is ISO 8601 with a timezone. */
export interface LogEvent {
  event: string
  ts: string
  data: Record<string, Scalar>
  source_id?: string
}

/** core Report: decided by core only. The web shows it and never changes it. */
export interface Violation {
  rule_id: string
  entity: string
  message: string
  timeline: LogEvent[]
  offending_index: number
}

export interface RuleResult {
  rule_id: string
  source: string
  status: 'pass' | 'violation'
  violations: Violation[]
  /** Events in the run this rule is about; 0 with "pass" means it was not tested. */
  checked_events?: number
}

export interface Report {
  results: RuleResult[]
}

/** C3 endpoint 5. */
export interface RunResponse {
  events: LogEvent[]
  report: Report
}

/** C3 endpoint 6. Always advisory: it never changes the verdict. */
export interface Explanation {
  text: string
  advisory: boolean
  cached: boolean
}

/** C3 endpoint 3 (200): the spec passed core's self-test. */
export interface SealResponse {
  ok: true
  spec_yaml: string
}

/** One confirmed example where core disagrees with the owner (C3 seal 422 `failures`). */
export interface SelfTestFailure {
  rule_id: string
  example_index: number
  timeline: TimelineEvent[]
  expected: boolean
  got: boolean
}

/** RFC 9457 problem details + stable `code` (C3 errors). */
export interface ApiProblem {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
  failures?: SelfTestFailure[] // compile_failed only
}
