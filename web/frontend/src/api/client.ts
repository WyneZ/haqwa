/**
 * The ONLY place the UI talks to the server.
 *
 * Mock mode (default until the FastAPI app exists) answers from real spike data in
 * `mocks.ts`. Set VITE_USE_MOCK=false (e.g. in web/frontend/.env.local) to call the
 * real `/api/v1` endpoints. Screens never know which one they are using.
 */
import { mockApplyAnswers, mockClarify } from './mocks'
import type { Answer, AnswersResponse, ApiProblem, ClarifyResponse, Rule } from './types'

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

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
  return USE_MOCK ? mockClarify(rules) : post<ClarifyResponse>('/clarify', { rules })
}

/** C3 endpoint 2: one rule + the owner's Yes/No answers -> updated rule. */
export function applyAnswers(rule: Rule, answers: Answer[]): Promise<AnswersResponse> {
  return USE_MOCK ? mockApplyAnswers(rule, answers) : post<AnswersResponse>('/answers', { rule, answers })
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
