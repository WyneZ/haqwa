/**
 * The ONLY place the UI talks to the server.
 *
 * Mock mode (default until the FastAPI app exists) answers from real data in
 * `fixtures.ts` and `runFixtures.ts`. Set VITE_USE_MOCK=false (e.g. in
 * web/frontend/.env.local) to call the real `/api/v1` endpoints. Screens never know
 * which one they are using.
 */
import { mockApplyAnswers, mockClarify, mockExplain, mockListScenarios, mockRun } from './mocks'
import type {
  Answer,
  AnswersResponse,
  ApiProblem,
  ClarifyResponse,
  Explanation,
  Rule,
  RunResponse,
  Scenario,
  Spec,
  Violation,
} from './types'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
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
    throw new ApiError(problem.detail ?? problem.title ?? res.statusText, res.status, problem.code)
  }
  return (await res.json()) as T
}

/** C3 endpoint 1: rule texts -> parsed rules + owner questions. */
export function clarifyRules(rules: string[]): Promise<ClarifyResponse> {
  return USE_MOCK ? mockClarify(rules) : request<ClarifyResponse>('/clarify', { rules })
}

/** C3 endpoint 2: one rule + the owner's Yes/No answers -> updated rule. */
export function applyAnswers(rule: Rule, answers: Answer[]): Promise<AnswersResponse> {
  return USE_MOCK
    ? mockApplyAnswers(rule, answers)
    : request<AnswersResponse>('/answers', { rule, answers })
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

/** C3 endpoint 6: plain-English explanation of one violation. Advisory only. */
export function explainViolation(rule: Rule, violation: Violation): Promise<Explanation> {
  return USE_MOCK
    ? mockExplain(rule, violation)
    : request<Explanation>('/explain', { rule, violation })
}

/** Plain-English message for the owner. Never shows stack traces or raw JSON. */
export function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'gemini_quota') {
      return 'The AI has reached its free limit for now. Please try again in a little while.'
    }
    if (error.status === 503) {
      return 'The AI is very busy right now. Please try again in a minute.'
    }
    return `Something went wrong (${error.status}). ${error.message}`
  }
  return 'Could not reach Haqwa. Check your connection and try again.'
}
