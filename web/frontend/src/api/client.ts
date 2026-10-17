/**
 * The ONLY place the UI talks to the server.
 *
 * Mock mode (default for the demo) answers from recorded data in
 * `fixtures.ts` and `runFixtures.ts`. Set VITE_USE_MOCK=false (e.g. in
 * web/frontend/.env.local) to call the real `/api/v1` endpoints. Screens never know
 * which one they are using.
 */
import {
  mockApplyAnswers,
  mockCheckAgentSession,
  mockClarify,
  mockCreateAgentSession,
  mockExplain,
  mockGetAgentSession,
  mockListScenarios,
  mockRun,
  mockSeal,
} from './mocks'
import type {
  AnswerV2,
  AnswersResponse,
  AgentFault,
  AgentSession,
  AgentSessionStatus,
  ApiProblem,
  ClarifyResponse,
  Explanation,
  LogEvent,
  RuleV2,
  RunResponse,
  Scenario,
  SealResponse,
  SelfTestFailure,
  Spec,
  TraceSummary,
  TraceVocabulary,
  Violation,
} from './types'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly problem: ApiProblem

  constructor(message: string, status: number, problem: ApiProblem = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = problem.code
    this.problem = problem
  }
}

/** The self-test failures of a `compile_failed` error, or [] for any other error. */
export function selfTestFailures(error: unknown): SelfTestFailure[] {
  return error instanceof ApiError && error.code === 'compile_failed'
    ? (error.problem.failures ?? [])
    : []
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let problem: ApiProblem = {}
    try {
      problem = (await res.json()) as ApiProblem
    } catch {
      // body was not JSON; keep the HTTP status text
    }
    throw new ApiError(problem.detail ?? problem.title ?? res.statusText, res.status, problem)
  }
  return (await res.json()) as T
}

/** C3 endpoint 1: rule texts -> parsed rules + owner questions. */
export function clarifyRules(
  rules: string[],
  vocabulary?: TraceVocabulary,
): Promise<ClarifyResponse> {
  return USE_MOCK
    ? mockClarify(rules)
    : request<ClarifyResponse>('/clarify', { rules, ...(vocabulary ? { vocabulary } : {}) })
}

/** C3 trace summary; mock mode mirrors only the fields needed for presentation. */
export async function summarizeTrace(events: unknown[], extraEvents: string[]): Promise<TraceSummary> {
  if (!USE_MOCK) {
    const result = await request<{ summary: TraceSummary }>('/traces', {
      events,
      extra_events: extraEvents,
    })
    return result.summary
  }
  const log = events as LogEvent[]
  const event_counts: Record<string, number> = {}
  const fields = new Set<string>()
  const times: string[] = []
  for (const item of log) {
    event_counts[item.event] = (event_counts[item.event] ?? 0) + 1
    Object.keys(item.data ?? {}).forEach((field) => fields.add(field))
    if (item.ts) times.push(item.ts)
  }
  times.sort((a, b) => Date.parse(a) - Date.parse(b))
  const names = [...new Set([...Object.keys(event_counts), ...extraEvents])].sort()
  const fieldNames = [...fields].sort()
  return {
    event_count: log.length,
    event_counts,
    first_ts: times[0] ?? null,
    last_ts: times.at(-1) ?? null,
    fields: fieldNames,
    field_values: {},
    entity_candidates: fieldNames.filter((field) => field.endsWith('_id')),
    vocabulary: { events: names, fields: fieldNames, field_values: {} },
  }
}

/** C3 endpoint 2: one rule + the owner's Yes/No answers -> updated rule. */
export function applyAnswers(
  rule: RuleV2, answers: AnswerV2[], vocabulary?: TraceVocabulary,
): Promise<AnswersResponse> {
  return USE_MOCK
    ? mockApplyAnswers(rule, answers)
    : request<AnswersResponse>('/answers', { rule, answers, ...(vocabulary ? { vocabulary } : {}) })
}

/**
 * C3 endpoint 3: core compiles the confirmed rules and replays every owner answer
 * (self-test). Throws ApiError `compile_failed` with `failures` if core disagrees.
 */
export function sealSpec(spec: Spec, vocabulary?: TraceVocabulary): Promise<SealResponse> {
  return USE_MOCK
    ? mockSeal(spec)
    : request<SealResponse>('/seal', { spec, ...(vocabulary ? { vocabulary } : {}) })
}

/** C3 endpoint 4: the demo scenarios (agents + faults). */
export function listScenarios(): Promise<Scenario[]> {
  return USE_MOCK ? mockListScenarios() : request<Scenario[]>('/scenarios')
}

/** C3 endpoint 5: run one scenario and check it against the spec (core decides). */
export function runScenario(spec: Spec, scenarioId: string): Promise<RunResponse> {
  return USE_MOCK
    ? mockRun(spec, scenarioId)
    : request<RunResponse>('/runs', { spec, scenario_id: scenarioId })
}

/** Create a private MCP shop for an external agent. */
export function createAgentSession(fault: AgentFault): Promise<AgentSession> {
  return USE_MOCK
    ? mockCreateAgentSession(fault)
    : request<AgentSession>('/agent-sessions', { fault })
}

/** Read the calls made in one live agent session. */
export async function getAgentSession(id: string): Promise<AgentSessionStatus> {
  if (!USE_MOCK) return request<AgentSessionStatus>(`/agent-sessions/${encodeURIComponent(id)}`)
  const session = await mockGetAgentSession(id)
  if (!session) {
    throw new ApiError('Session not found or expired', 404, { code: 'session_not_found' })
  }
  return session
}

/** Ask the backend checker for a session verdict. */
export async function checkAgentSession(id: string, spec: Spec): Promise<RunResponse> {
  if (!USE_MOCK) {
    return request<RunResponse>(`/agent-sessions/${encodeURIComponent(id)}/check`, { spec })
  }
  const response = await mockCheckAgentSession(id, spec)
  if (!response) {
    throw new ApiError('Session not found or expired', 404, { code: 'session_not_found' })
  }
  return response
}

export function checkEvents(spec: Spec, events: LogEvent[]): Promise<RunResponse> {
  return USE_MOCK
    ? Promise.reject(new ApiError('Checking your own events needs the real API', 501))
    : request<RunResponse>('/runs', { spec, events })
}

/** C3 endpoint 6: plain-English explanation of one violation. Advisory only. */
export function explainViolation(rule: RuleV2, violation: Violation): Promise<Explanation> {
  return USE_MOCK
    ? mockExplain(rule, violation)
    : request<Explanation>('/explain', { rule, violation })
}

/** Plain-English message for the owner. Never shows stack traces or raw JSON. */
export function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'compile_failed') {
      return 'Some answers don’t match how Haqwa checks these rules. Please answer them again.'
    }
    if (error.code === 'session_not_found') {
      return 'This session expired or was not found. Create a new one.'
    }
    if (error.code === 'session_limit') {
      return 'Too many live sessions right now. Please try again in a few minutes.'
    }
    if (error.code === 'rate_limited') {
      // The server puts the wait in `detail` ("... retry in 37 seconds."); no Retry-After header.
      const seconds = /(\d+) seconds?/.exec(error.message)?.[1]
      const wait = seconds ? `${seconds} seconds` : 'a minute'
      return `Too many requests right now. Please wait ${wait} and try again.`
    }
    if (error.code === 'gemini_quota') {
      return 'The AI has reached its usage limit for now. Please try again in a little while.'
    }
    if (error.code === 'invalid_events' || error.code === 'invalid_request') {
      return error.problem.detail ?? error.message
    }
    if (error.status === 503) {
      return 'The AI is very busy right now. Please try again in a minute.'
    }
    return `Something went wrong (${error.status}). ${error.message}`
  }
  return 'Could not reach Haqwa. Check your connection and try again.'
}
