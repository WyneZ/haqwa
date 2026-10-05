/**
 * MOCK MODE ONLY. Delete this file's use (in client.ts) once FastAPI is wired.
 *
 * `mockApplyAnswers` copies ai.clarify.apply_answers so the screen can be built before
 * the API exists. It is NOT the source of truth: the real rule update happens in
 * Python (`POST /api/v1/answers`). The web never decides anything in production.
 */
import { DEMO_RESULTS } from './fixtures'
import { DEMO_EXPLANATIONS, DEMO_RUNS, DEMO_SCENARIOS } from './runFixtures'
import type {
  Answer,
  AnswersResponse,
  ClarifyResponse,
  ClarifyResult,
  Explanation,
  Rule,
  RunResponse,
  Scenario,
  Spec,
  Violation,
} from './types'

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export async function mockClarify(rules: string[]): Promise<ClarifyResponse> {
  await delay(700)
  const results: ClarifyResult[] = rules.map(
    (text) =>
      DEMO_RESULTS.find((r) => r.source === text) ?? {
        source: text,
        status: 'unsupported',
        reason: 'Mock mode only knows the three demo rules. Start the API to try your own.',
      },
  )
  return { cached: true, results }
}

export async function mockApplyAnswers(rule: Rule, answers: Answer[]): Promise<AnswersResponse> {
  await delay(300)
  const except = [...rule.except]
  const examples = [...rule.confirmed_examples]
  const mismatches: string[] = []
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

  for (const { question: q, allowed } of answers) {
    const violation = !allowed
    if (q.kind === 'confirmation' && q.expected_violation !== undefined) {
      if (violation !== q.expected_violation) {
        mismatches.push(`${q.id}: owner answered the opposite of the expected result`)
        continue
      }
    }
    if (q.kind === 'decision' && allowed && q.if_yes && !except.some((e) => same(e, q.if_yes))) {
      except.push(q.if_yes)
    }
    const example = { timeline: q.timeline, violation }
    if (!examples.some((e) => same(e, example))) examples.push(example)
  }
  return { rule: { ...rule, except, confirmed_examples: examples }, mismatches }
}

export async function mockListScenarios(): Promise<Scenario[]> {
  await delay(200)
  return DEMO_SCENARIOS
}

/**
 * Returns the recorded run of the demo rules. It does NOT check `spec`: it only keeps
 * the results of rules that are in `spec`, so the screens match what the owner confirmed.
 * The real check (`POST /api/v1/runs`) runs core against the exact spec.
 */
export async function mockRun(spec: Spec, scenarioId: string): Promise<RunResponse> {
  await delay(600)
  const run = DEMO_RUNS[scenarioId]
  if (!run) throw new Error(`Mock mode does not know scenario ${scenarioId}.`)
  const ids = new Set(spec.rules.map((r) => r.id))
  return { ...run, report: { results: run.report.results.filter((r) => ids.has(r.rule_id)) } }
}

export async function mockExplain(rule: Rule, violation: Violation): Promise<Explanation> {
  await delay(900)
  const text = DEMO_EXPLANATIONS[`${rule.id}|${violation.entity}|${violation.message}`]
  return {
    text: text ?? 'Mock mode has no AI explanation for this case. Start the API to ask the AI.',
    advisory: true,
    cached: true,
  }
}
