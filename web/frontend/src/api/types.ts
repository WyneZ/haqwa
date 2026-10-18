/**
 * C3 v2 Web API shapes (docs/contracts.md, DRAFT 2026-10-16).
 *
 * Hand-written until the agreed OpenAPI generation step. Rules use only the v2 AST.
 */

export type Scalar = string | number | boolean

export interface TimelineEvent {
  event: string
  data: Record<string, Scalar>
  /** Offset from the first event, ISO 8601 duration (e.g. "P1DT1H"). Set by core for time rules. */
  at?: string | null
}

export interface ConditionV2 {
  field: string
  op: 'eq' | 'ne' | 'in' | 'gt' | 'ge' | 'lt' | 'le'
  value: Scalar | Scalar[]
}

export interface ConfirmedExample {
  timeline: TimelineEvent[]
  violation: boolean
}

export interface SelectNode {
  id: string
  type: 'select'
  event: string
  where: ConditionV2[]
  exclude: ConditionV2[]
}

export interface CountNode {
  id: string
  type: 'count'
  of: string
  op: 'le' | 'lt' | 'eq' | 'ge'
  value: number
  since: string[]
}

export interface NoneAfterNode {
  id: string
  type: 'none_after'
  of: string
  after: string
  since: string[]
}

export interface EveryPrecededByNode {
  id: string
  type: 'every_preceded_by'
  of: string
  by: string
  since: string[]
}

export interface EveryFollowedWithinNode {
  id: string
  type: 'every_followed_within'
  start: string
  by: string
  within: string
  since: string[]
}

export interface SumCompareNode {
  id: string
  type: 'sum_compare'
  left: { of: string; field: string }
  op: Exclude<ConditionV2['op'], 'in'>
  right: { of: string; field: string }
}

export interface FieldCompareNode {
  id: string
  type: 'field_compare'
  of: string
  a: string
  op: 'eq' | 'ne'
  b: string
}

export interface AllOfNode {
  id: string
  type: 'all_of'
  children: string[]
}

export type NodeV2 = SelectNode | CountNode | NoneAfterNode | EveryPrecededByNode
  | EveryFollowedWithinNode | SumCompareNode | FieldCompareNode | AllOfNode

export interface RuleV2 {
  id: string
  source: string
  version: 2
  per: string
  root: string
  nodes: NodeV2[]
}

/** B2 target shape; the sidecar-to-rule bridge lives only in lib/specRule.ts. */
export type SpecRule = RuleV2 & { confirmed_examples: ConfirmedExample[] }

export type PatchCondition =
  | { field: string; op: 'eq' | 'ne'; value: string }
  | { field: string; op: 'in'; values: string[] }

export type Patch =
  | { op: 'add_reset'; node_id: string; event: string }
  | { op: 'add_exclude'; select_ids: string[]; condition: PatchCondition }

interface QuestionBase {
  id: string // "d1", "d2" … decisions; "c1", "c2" … confirmations
  text: string
  timeline: TimelineEvent[]
}

export type QuestionV2 = QuestionBase & (
  | { kind: 'decision'; why: string | null; patch: Patch; expected_violation: null }
  | { kind: 'confirmation'; why: null; patch: null; expected_violation: boolean }
)

export type ClarifyResult =
  | { source: string; status: 'supported'; rule: RuleV2; meaning: string; questions: QuestionV2[]; reason: null }
  | { source: string; status: 'unsupported'; rule: null; meaning: null; questions: null; reason: string | null }

export interface ClarifyResponse {
  cached: boolean
  results: ClarifyResult[]
}

export interface AnswerV2 {
  question: QuestionV2
  allowed: boolean
}

export interface AnswersResponse {
  rule: RuleV2
  /** Code-rendered meaning of the UPDATED rule (after Yes decisions). What core will enforce. */
  meaning: string
  confirmed_examples: ConfirmedExample[]
  mismatches: string[]
}

/** C1 spec: what screen 1 hands to screen 2. */
export interface Spec {
  version: 2
  rules: SpecRule[]
}

/** C3 endpoint 4: one demo scenario (Track B `demo.list_scenarios()`). */
export interface Scenario {
  id: string
  title: string
  fault: string
  agent: 'naive' | 'fixed' | 'gemini'
  description: string
  expected: 'violation' | 'pass' | 'unknown'
  kind: 'scripted' | 'recorded' | 'live'
}

export type AgentFault = 'timeout_after_commit' | 'stale_state'

export interface AgentSession {
  session_id: string
  fault: AgentFault
  mcp_url: string
  task: string
  expires_at: string
}

export interface AgentToolCall {
  tool: string
  arguments: Record<string, unknown>
  ok: boolean
  error: string | null
  at: string
}

export interface AgentSessionStatus {
  session_id: string
  fault: AgentFault
  expires_at: string
  calls: AgentToolCall[]
}

export interface EventsSession {
  session_id: string
  kind: 'events'
  ingest_url: string
  expires_at: string
  snippet: string
}

export interface EventsSessionStatus {
  session_id: string
  kind: 'events'
  expires_at: string
  events: LogEvent[]
  calls: AgentToolCall[]
}

export interface TraceVocabulary {
  events: string[]
  fields: string[]
  field_values: Record<string, string[]>
  numeric_fields?: string[]
}

export interface TraceSummary {
  event_count: number
  event_counts: Record<string, number>
  first_ts: string | null
  last_ts: string | null
  fields: string[]
  field_values: Record<string, string[]>
  entity_candidates: string[]
  vocabulary: TraceVocabulary
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

/** One rule found in an uploaded policy document, with the document text behind it. */
export interface ExtractedRule {
  text: string
  quote: string
}

/** POST /policy-documents: the rules Gemini found; every quote is verified in the document. */
export interface PolicyDocumentResult {
  filename: string
  kind: 'text' | 'docx' | 'pdf'
  chars: number
  rules: ExtractedRule[]
  cached: boolean
}

export interface SuggestedEvent {
  name: string
  description: string
}

export interface SuggestedVocabulary {
  events: SuggestedEvent[]
  entity_field: string
  fields: string[]
}
