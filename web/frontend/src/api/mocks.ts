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
  AgentFault,
  AgentSession,
  AgentSessionStatus,
  AgentToolCall,
  ClarifyResponse,
  ClarifyResult,
  Explanation,
  LogEvent,
  Rule,
  RunResponse,
  Scenario,
  SealResponse,
  Spec,
  Violation,
} from './types'

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const AGENT_TASKS: Record<AgentFault, string> = {
  timeout_after_commit: 'Create order A-1 for 50 and charge it.',
  stale_state: 'Process fulfilment for order A-1.',
}

const AGENT_CALLS: Record<AgentFault, Omit<AgentToolCall, 'at'>[]> = {
  timeout_after_commit: [
    { tool: 'create_order', arguments: { order_id: 'A-1', amount: 50 }, ok: true, error: null },
    {
      tool: 'charge_payment',
      arguments: { order_id: 'A-1', amount: 50 },
      ok: false,
      error: 'Request timed out',
    },
    {
      tool: 'charge_payment',
      arguments: { order_id: 'A-1', amount: 50, idempotency_key: 'charge-A-1-50-1' },
      ok: true,
      error: null,
    },
  ],
  stale_state: [
    { tool: 'get_order', arguments: { order_id: 'A-1' }, ok: true, error: null },
    { tool: 'ship_order', arguments: { order_id: 'A-1' }, ok: true, error: null },
  ],
}

let agentSession: AgentSession | null = null
let agentCreatedAt = 0
let agentPollCount = 0

function currentAgentSession(id: string): AgentSession | null {
  return agentSession?.session_id === id && Date.now() < Date.parse(agentSession.expires_at)
    ? agentSession
    : null
}

/** One local mock session, with calls appearing on successive status polls. */
export async function mockCreateAgentSession(fault: AgentFault): Promise<AgentSession> {
  await delay(200)
  agentCreatedAt = Date.now()
  agentPollCount = 0
  agentSession = {
    session_id: 'mock',
    fault,
    mcp_url: `http://localhost:8000/agent/${fault === 'timeout_after_commit' ? 'timeout' : 'stale'}/mcp?session=mock`,
    task: AGENT_TASKS[fault],
    expires_at: new Date(agentCreatedAt + 30 * 60 * 1000).toISOString(),
  }
  return agentSession
}

export async function mockGetAgentSession(id: string): Promise<AgentSessionStatus | null> {
  await delay(150)
  const session = currentAgentSession(id)
  if (!session) return null
  const calls = AGENT_CALLS[session.fault]
  agentPollCount = Math.min(agentPollCount + 1, calls.length)
  return {
    session_id: session.session_id,
    fault: session.fault,
    expires_at: session.expires_at,
    calls: calls.slice(0, agentPollCount).map((call, index) => ({
      ...call,
      at: new Date(agentCreatedAt + index * 2000).toISOString(),
    })),
  }
}

/** Mock verdicts are fixtures; only the real API checks the submitted spec. */
export async function mockCheckAgentSession(id: string, spec: Spec): Promise<RunResponse | null> {
  const session = currentAgentSession(id)
  if (!session) return null
  if (agentPollCount === 0) {
    return {
      events: [],
      report: {
        results: spec.rules.map((rule) => ({
          rule_id: rule.id,
          source: rule.source,
          status: 'pass',
          violations: [],
          checked_events: 0,
        })),
      },
    }
  }
  if (session.fault === 'stale_state') {
    const events: LogEvent[] = ['order_created', 'charged', 'cancelled', 'shipped'].map(
      (event, index) => ({
        event,
        ts: new Date(agentCreatedAt + index * 1000).toISOString(),
        data: { order_id: 'A-1', ...(index < 2 ? { amount: 50 } : {}) },
      }),
    )
    const shipRule = spec.rules.find(
      (rule) => rule.pattern === 'never_after' && rule.event === 'shipped' && rule.after === 'cancelled',
    )
    const chargeRule = spec.rules.find((rule) => rule.id === 'no-double-charge')
    return {
      events,
      report: {
        results: [
          ...(chargeRule
            ? [{ rule_id: chargeRule.id, source: chargeRule.source, status: 'pass' as const, violations: [] }]
            : []),
          ...(shipRule
            ? [{
                rule_id: shipRule.id,
                source: shipRule.source,
                status: 'violation' as const,
                violations: [{
                  rule_id: shipRule.id,
                  entity: 'A-1',
                  message: "'shipped' happened after 'cancelled'",
                  timeline: events,
                  offending_index: 3,
                }],
              }]
            : []),
        ],
      },
    }
  }
  return mockRun(spec, 'payment_timeout_naive')
}

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

/** Mock mode cannot run core's self-test: it always says the spec is fine. */
export async function mockSeal(spec: Spec): Promise<SealResponse> {
  await delay(300)
  return { ok: true, spec_yaml: `# mock mode: ${spec.rules.length} rule(s), not checked by core\n` }
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
