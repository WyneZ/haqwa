import type { AgentFault, RunResponse, Scenario } from '../api/types'

export type RunSource =
  | { kind: 'scenario'; scenario: Scenario }
  | { kind: 'agent'; sessionId: string; fault: AgentFault; callCount: number }
  | { kind: 'trace'; name: string; eventCount: number }

/** One finished test run and what core decided. UI state only. */
export interface Run {
  source: RunSource
  response: RunResponse
}
