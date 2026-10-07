/**
 * How to show core's verdict for one rule. Presentation only: core decides pass/fail.
 *
 * A rule can "pass" only because nothing it talks about happened in the run (e.g. a
 * shipping rule when the agent never ships). Core reports that as `checked_events: 0`;
 * the UI shows it as "Not tested" so a green badge always means the rule was exercised.
 */
import type { RuleResult } from '../api/types'

export type VerdictKind = 'broken' | 'pass' | 'untested'

export function verdictKind(r: RuleResult): VerdictKind {
  if (r.status === 'violation') return 'broken'
  // Older responses and mock fixtures have no `checked_events`: treat them as tested.
  return r.checked_events === 0 ? 'untested' : 'pass'
}
