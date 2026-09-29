/**
 * MOCK MODE ONLY. Delete this file's use (in client.ts) once FastAPI is wired.
 *
 * `mockApplyAnswers` copies ai.clarify.apply_answers so the screen can be built before
 * the API exists. It is NOT the source of truth: the real rule update happens in
 * Python (`POST /api/v1/answers`). The web never decides anything in production.
 */
import { DEMO_RESULTS } from './fixtures'
import type { Answer, AnswersResponse, ClarifyResponse, ClarifyResult, Rule } from './types'

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
