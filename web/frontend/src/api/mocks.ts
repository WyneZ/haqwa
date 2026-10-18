/**
 * MOCK MODE ONLY. Fixture verdicts and a small patch test double for UI development.
 *
 * `mockApplyAnswers` mirrors answers_v2's transport contract. It is NOT the source
 * of truth: the real rule update happens in
 * Python (`POST /api/v1/answers`). The web never decides anything in production.
 */
import { DEMO_RESULTS } from './fixtures'
import { patchText } from '../lib/words'
import { DEMO_EXPLANATIONS, DEMO_RUNS, DEMO_SCENARIOS } from './runFixtures'
import type {
  AnswerV2,
  AnswersResponse,
  AgentFault,
  AgentSession,
  AgentSessionStatus,
  AgentToolCall,
  ClarifyResponse,
  ClarifyResult,
  Explanation,
  EventsSession,
  EventsSessionStatus,
  LogEvent,
  PolicyDocumentResult,
  RuleV2,
  RunResponse,
  Scenario,
  SealResponse,
  Spec,
  TraceVocabulary,
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

let eventsSession: EventsSession | null = null
let eventsVocabulary: TraceVocabulary | null = null

/** Mock of the events-session transport; external reporting uses the real API. */
export async function mockCreateEventsSession(vocabulary: TraceVocabulary): Promise<EventsSession> {
  await delay(100)
  const id = `mock-events-${Date.now()}`
  const ingest_url = `http://localhost:8000/api/v1/agent-sessions/${id}/events`
  eventsVocabulary = vocabulary
  eventsSession = {
    session_id: id,
    kind: 'events',
    ingest_url,
    expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    snippet: `curl -X POST "${ingest_url}" -H "Content-Type: application/json" -d '{"event":"${vocabulary.events[0]}","ts":"2026-10-18T00:00:00Z","data":{}}'`,
  }
  return eventsSession
}

export async function mockGetEventsSession(id: string): Promise<EventsSessionStatus | null> {
  await delay(100)
  if (eventsSession?.session_id !== id || Date.now() >= Date.parse(eventsSession.expires_at)) return null
  return { session_id: id, kind: 'events', expires_at: eventsSession.expires_at, events: [], calls: [] }
}

export async function mockCheckEventsSession(id: string, spec: Spec): Promise<RunResponse | null> {
  if (!eventsVocabulary || eventsSession?.session_id !== id || Date.now() >= Date.parse(eventsSession.expires_at)) return null
  return {
    events: [],
    report: { results: spec.rules.map((rule) => ({ rule_id: rule.id, source: rule.source, status: 'pass', violations: [], checked_events: 0 })) },
  }
}

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
    const shipRule = spec.rules.find((rule) => rule.nodes.some((node) =>
      node.type === 'none_after'
      && rule.nodes.some(n => n.type === 'select' && n.id === node.of && n.event === 'shipped')
      && rule.nodes.some(n => n.type === 'select' && n.id === node.after && n.event === 'cancelled'),
    ))
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
        rule: null,
        meaning: null,
        questions: null,
        reason: 'Mock mode only knows the three demo rules. Start the API to try your own.',
      },
  )
  return { cached: true, results }
}

/** Mock-only patch application; never imported by the real API path to decide a verdict. */
export async function mockApplyAnswers(rule: RuleV2, answers: AnswerV2[]): Promise<AnswersResponse> {
  await delay(300)
  const updated = structuredClone(rule)
  const examples: AnswersResponse['confirmed_examples'] = []
  const mismatches: string[] = []
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

  for (const { question: q, allowed } of answers) {
    const violation = !allowed
    if (q.kind === 'confirmation') {
      if (violation !== q.expected_violation) {
        const expected = q.expected_violation ? 'not allowed' : 'allowed'
        mismatches.push(`${q.id}: owner answered the opposite of '${expected}'`)
        continue
      }
    }
    if (q.kind === 'decision' && allowed) {
      const patch = q.patch
      if (patch.op === 'add_reset') {
        const node = updated.nodes.find(n => n.id === patch.node_id)
        if (node && 'since' in node && !node.since.includes(patch.event)) node.since.push(patch.event)
      } else {
        const condition = patch.condition.op === 'in'
          ? { field: patch.condition.field, op: patch.condition.op, value: patch.condition.values }
          : patch.condition
        for (const node of updated.nodes) {
          if (node.type === 'select' && patch.select_ids.includes(node.id)
            && !node.exclude.some(c => same(c, condition))) node.exclude.push(structuredClone(condition))
        }
      }
    }
    const example = { timeline: q.timeline, violation }
    if (!examples.some((e) => same(e, example))) examples.push(example)
  }
  // Mock-only preview of the final meaning. The real API renders it in Python (render_v2);
  // here we append the accepted decisions to the fixture's parsed meaning.
  const parsed = DEMO_RESULTS.find((r) => r.status === 'supported' && r.rule.id === rule.id)
  const accepted = answers
    .filter(({ question: q, allowed }) => q.kind === 'decision' && allowed)
    .map(({ question: q }) => (q.kind === 'decision' ? patchText(q.patch) : ''))
  const base = parsed?.meaning ?? rule.source
  const meaning = accepted.length ? `${base} Exceptions: ${[...new Set(accepted)].join(' ')}` : base
  return { rule: updated, meaning, confirmed_examples: examples, mismatches }
}

/** MOCK ONLY: pretends the uploaded file contains the three demo rules. */
export async function mockPolicyDocument(filename: string): Promise<PolicyDocumentResult> {
  await delay(600)
  const rules = DEMO_RESULTS.map((r) => ({ text: r.source, quote: r.source }))
  const chars = rules.map((r) => r.text).join('\n').length
  return { filename, kind: 'text', chars, rules, cached: true }
}

/** Mock mode cannot run core's self-test: it always says the spec is fine. */
export async function mockSeal(spec: Spec): Promise<SealResponse> {
  await delay(300)
  // JSON is valid YAML 1.2; preserve the actual v2 shape without a YAML dependency.
  return { ok: true, spec_yaml: `# MOCK ONLY: not checked by core\n${JSON.stringify(spec, null, 2)}\n` }
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

export async function mockExplain(rule: RuleV2, violation: Violation): Promise<Explanation> {
  await delay(900)
  const text = DEMO_EXPLANATIONS[`${rule.id}|${violation.entity}|${violation.message}`]
  return {
    text: text ?? 'Mock mode has no AI explanation for this case. Start the API to ask the AI.',
    advisory: true,
    cached: true,
  }
}
