import { useState } from 'react'
import { friendlyError, listScenarios, runScenario } from '../api/client'
import type { Spec } from '../api/types'
import { ExplainBox } from '../components/ExplainBox'
import { SpecDownload } from '../components/SpecDownload'
import { Timeline } from '../components/Timeline'
import { Verdicts } from '../components/Verdicts'
import type { Run } from '../lib/run'
import { checkerFact, entityNoun, humanize } from '../lib/words'

interface Props {
  spec: Spec
  specYaml: string
  run: Run
  onRun: (run: Run) => void
  onBack: () => void
}

/**
 * Screen 3 (Results): which rule broke, for which entity, at which event — all from
 * core's report. The AI explanation sits apart and is labelled as a suggestion.
 */
export function ResultsScreen({ spec, specYaml, run, onRun, onBack }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { source, response } = run
  const violations = response.report.results.flatMap((r) => r.violations)
  const heading =
    source.kind === 'scenario'
      ? `Scenario: ${source.scenario.title}`
      : source.kind === 'agent'
        ? `Your agent · live (${source.fault === 'timeout_after_commit' ? 'payment timeout' : 'stale order status'})`
        : `Your events: ${source.name} (${source.eventCount} events)`

  /** Same fault, fixed agent: the "before / after" step of the demo. */
  async function testFixed() {
    if (source.kind !== 'scenario') return
    setBusy(true)
    setError(null)
    try {
      const fixed = (await listScenarios()).find(
        (s) => s.fault === source.scenario.fault && s.agent === 'fixed',
      )
      if (!fixed) throw new Error('no fixed agent for this scenario')
      onRun({
        source: { kind: 'scenario', scenario: fixed },
        response: await runScenario(spec, fixed.id),
      })
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="stage stage--wide">
      <h1 className="report__context">
        {heading}
      </h1>

      {violations.length === 0 && source.kind !== 'trace' && (
        <section className="card card--pass">
          <h2 className="card__title">✓ All rules held</h2>
          <p>The agent did nothing your rules forbid.</p>
          <p className="card__lead">What the agent did:</p>
          <Timeline events={response.events} />
        </section>
      )}

      {violations.map((v) => {
        const rule = spec.rules.find((r) => r.id === v.rule_id)
        const start = Math.max(0, v.offending_index - 199)
        const visible = source.kind === 'trace' ? v.timeline.slice(start, start + 200) : v.timeline
        return (
          <section key={`${v.rule_id}:${v.entity}`} className="card card--fail">
            <p className="verdict">Broken</p>
            <h2 className="card__title">
              {humanize(rule ? entityNoun(rule.per) : 'item')} {v.entity} broke “
              {rule?.source ?? v.rule_id}”
            </h2>
            {source.kind === 'trace' && (
              <p className="card__lead">
                Showing {visible.length} of {response.events.length} events: this{' '}
                {rule ? entityNoun(rule.per) : 'item'}&apos;s events up to the one that broke the rule
              </p>
            )}
            <Timeline
              events={visible}
              offendingIndex={v.offending_index - (source.kind === 'trace' ? start : 0)}
            />
            <p className="fact">
              <span className="tag tag--checker">Checker</span>
              <span>{checkerFact(v.message)}</span>
            </p>
            {rule && <ExplainBox rule={rule} violation={v} />}
          </section>
        )
      })}

      <section className="card card--rules">
        <h2 className="card__title card__title--small">All rules</h2>
        <Verdicts results={response.report.results} />
        <SpecDownload specYaml={specYaml} />
      </section>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
      <div className="card__actions report__actions">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          ← Back to test
        </button>
        {source.kind === 'scenario' && source.scenario.agent === 'naive' && (
          <button type="button" className="btn btn--primary" onClick={testFixed} disabled={busy}>
            {busy ? 'Running…' : 'Test the fixed agent →'}
          </button>
        )}
      </div>
    </main>
  )
}
