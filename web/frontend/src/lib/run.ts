import type { RunResponse, Scenario } from '../api/types'

/** One finished test run: which scenario, and what core decided. UI state only. */
export interface Run {
  scenario: Scenario
  response: RunResponse
}
