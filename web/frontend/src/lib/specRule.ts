import type { ConfirmedExample, RuleV2, SpecRule } from '../api/types'

/** B2 bridge: attach the current answers response's sidecar only when building a spec. */
export function toSpecRule(rule: RuleV2, confirmedExamples: ConfirmedExample[]): SpecRule {
  return { ...rule, confirmed_examples: confirmedExamples }
}
