import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { DEMO_RESULTS } from '../src/api/fixtures.ts'
import { mockApplyAnswers, mockCheckAgentSession, mockCreateAgentSession, mockRun, mockSeal } from '../src/api/mocks.ts'
import { toSpecRule } from '../src/lib/specRule.ts'

const supported = () => DEMO_RESULTS.filter((result) => result.status === 'supported')

test('fixture meaning, question, why and patches preserve the real G2 run verbatim', () => {
  const golden = JSON.parse(readFileSync(new URL('../../../spikes/clarify_v2/runs/g2_run3a.json', import.meta.url), 'utf8'))
  supported().forEach((result, index) => {
    const original = golden.rules[index]
    assert.equal(result.source, original.source)
    assert.equal(result.meaning, original.meaning)
    assert.deepEqual(result.questions.filter(q => q.kind === 'decision').map(q => ({
      id: q.id, question: q.text, why: q.why, patch: q.patch,
    })), original.decisions.map(d => ({ id: d.id, question: d.question, why: d.why, patch: d.patch })))
  })
})

test('G2 fixtures contain v2 rules, exact meanings, decisions and confirmations', () => {
  const rules = supported()
  assert.equal(rules.length, 3)
  assert.equal(rules.reduce((count, r) => count + r.questions.filter(q => q.kind === 'decision').length, 0), 6)
  for (const result of rules) {
    assert.equal(result.rule.version, 2)
    assert.ok(result.rule.nodes.some(n => n.id === result.rule.root))
    assert.ok(result.meaning.startsWith('For each order:'))
    assert.ok(result.questions.some(q => q.kind === 'confirmation'))
    for (const question of result.questions) {
      assert.ok(question.timeline.length >= 1)
      if (question.kind === 'decision') {
        assert.ok(question.timeline.length >= 2)
        assert.ok(question.patch && question.why)
      }
    }
  }
})

test('toSpecRule keeps sidecar examples without mutating the parsed rule', () => {
  const original = supported()[0].rule
  const examples = [{ timeline: [{ event: 'charged', data: {} }], violation: false }]
  const result = toSpecRule(original, examples)
  assert.deepEqual(result.confirmed_examples, examples)
  assert.equal('confirmed_examples' in original, false)
})

test('mock Yes patches deduplicate; No keeps the original rule', async () => {
  const original = supported()[0]
  const snapshot = JSON.stringify(original)
  const decisions = original.questions.filter(q => q.kind === 'decision')
  const answers = decisions.map(question => ({ question, allowed: true }))
  const result = await mockApplyAnswers(original.rule, [...answers, ...answers])
  const count = result.rule.nodes.find(n => n.type === 'count')
  const select = result.rule.nodes.find(n => n.type === 'select')
  assert.deepEqual(count?.since, ['refunded'])
  assert.equal(select?.exclude.length, 1)
  assert.equal(result.confirmed_examples.length, 2)
  assert.equal(result.confirmed_examples.every(e => !e.violation), true)
  assert.equal(JSON.stringify(original), snapshot)
  const no = await mockApplyAnswers(original.rule, decisions.map(question => ({ question, allowed: false })))
  assert.deepEqual(no.rule, original.rule)
  assert.equal(no.confirmed_examples.every(e => e.violation), true)
})

test('mock confirmation mismatch matches the API and is not recorded', async () => {
  const original = supported()[0]
  const question = original.questions.find(q => q.kind === 'confirmation' && q.expected_violation)
  assert.ok(question)
  const result = await mockApplyAnswers(original.rule, [{ question, allowed: true }])
  assert.deepEqual(result.mismatches, [`${question.id}: owner answered the opposite of 'not allowed'`])
  assert.deepEqual(result.confirmed_examples, [])
})

test('mock exemption covers both deadline selects and redo recomputes full evidence', async () => {
  const original = supported()[2]
  const questions = original.questions
  const answers = questions.map(question => ({ question, allowed: question.kind === 'decision' || !question.expected_violation }))
  const first = await mockApplyAnswers(original.rule, answers)
  assert.equal(first.rule.nodes.filter(n => n.type === 'select' && n.exclude.length === 1).length, 2)
  const redo = await mockApplyAnswers(original.rule, answers.map(a => a.question.kind === 'decision' ? { ...a, allowed: false } : a))
  assert.deepEqual(redo.rule, original.rule)
  assert.equal(redo.confirmed_examples.length, questions.length)
})

test('mock Define to Results uses v2 specs with fixture verdicts', async () => {
  const spec = { version: 2 as const, rules: supported().map(r => toSpecRule(r.rule, [])) }
  assert.equal((await mockSeal(spec)).ok, true)
  const response = await mockRun(spec, 'payment_timeout_naive')
  assert.ok(response.report.results.some(r => r.status === 'violation'))
  const session = await mockCreateAgentSession('stale_state')
  const checked = await mockCheckAgentSession(session.session_id, spec)
  assert.ok(checked?.report.results.some(r => r.rule_id === 'no-ship-after-cancel' && r.status === 'violation'))
})

test('mock answers return the final meaning: parsed meaning plus accepted decisions only', async () => {
  const original = supported()[0]
  const decisions = original.questions.filter(q => q.kind === 'decision')
  const yes = await mockApplyAnswers(original.rule, decisions.map(question => ({ question, allowed: true })))
  assert.ok(yes.meaning.startsWith(original.meaning))
  assert.ok(yes.meaning.includes('Exceptions:'))
  const no = await mockApplyAnswers(original.rule, decisions.map(question => ({ question, allowed: false })))
  assert.equal(no.meaning, original.meaning)
})
