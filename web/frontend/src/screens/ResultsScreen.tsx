import { useState } from 'react'
import { friendlyError, listScenarios, runScenario } from '../api/client'
import type { Spec } from '../api/types'
import { ExplainBox } from '../components/ExplainBox'
import { Timeline } from '../components/Timeline'
import { Verdicts } from '../components/Verdicts'
import type { Run } from '../lib/run'
import { entityNoun, humanize } from '../lib/words'

interface Props {
  spec: Spec
  run: Run
  onRun: (run: Run) => void
  onBack: () => void
}

/**
 * Screen 3 (Results): which rule broke, for which entity, at which event — all from
 * core's report. The AI explanation sits apart and is labelled as a suggestion.
 */
export function ResultsScreen({ spec, run, onRun, onBack }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { scenario, response } = run
  const violations = response.report.results.flatMap((r) => r.violations)

  /** Same fault, fixed agent: the "before / after" step of the demo. */
  async function testFixed() {
    setBusy(true)
    setError(null)
    try {
      const fixed = (await listScenarios()).find(
        (s) => s.fault === scenario.fault && s.agent === 'fixed',
      )
      if (!fixed) throw new Error('no fixed agent for this scenario')
      onRun({ scenario: fixed, response: await runScenario(spec, fixed.id) })
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="stage stage--wide">
      <p className="card__lead">Scenario: {scenario.title}</p>

      {violations.length === 0 && (
        <section className="card card--pass">
          <h2 className="card__title">✓ All rules held</h2>
          <p>The agent did nothing your rules forbid.</p>
          <p className="card__lead">What the agent did:</p>
          <Timeline events={response.events} />
        </section>
      )}

      {violations.map((v) => {
        const rule = spec.rules.find((r) => r.id === v.rule_id)
        return (
          <section key={`${v.rule_id}:${v.entity}`} className="card card--fail">
            <p className="verdict">Rule broken</p>
            <h2 className="card__title">
              {humanize(rule ? entityNoun(rule.per) : 'item')} {v.entity} broke “{rule?.source ?? v.rule_id}”
            </h2>
            <Timeline events={v.timeline} offendingIndex={v.offending_index} />
            {rule && <ExplainBox rule={rule} violation={v} />}
          </section>
        )
      })}

      <section className="card">
        <h2 className="card__title card__title--small">All rules</h2>
        <Verdicts results={response.report.results} />
      </section>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
      <div className="card__actions">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          ← Back to test
        </button>
        {scenario.agent === 'naive' && (
          <button type="button" className="btn btn--primary" onClick={testFixed} disabled={busy}>
            {busy ? 'Running…' : 'Test the fixed agent →'}
          </button>
        )}
      </div>
    </main>
  )
}
