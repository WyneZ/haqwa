import { useEffect, useState } from 'react'
import { friendlyError, listScenarios, runScenario } from '../api/client'
import type { Scenario, Spec } from '../api/types'
import { Timeline } from '../components/Timeline'
import { Verdicts } from '../components/Verdicts'
import { usePersistentState } from '../lib/persist'
import type { Run } from '../lib/run'
import { ruleTitle } from '../lib/words'

interface Props {
  spec: Spec
  run: Run | null
  onRun: (run: Run) => void
  onBack: () => void
  onSeeResults: () => void
}

/**
 * Screen 2 (Test): pick a demo agent + fault, run it, see what it did and core's verdict.
 * The run and the verdict come from the API; this screen only displays them.
 */
export function TestScreen({ spec, run, onRun, onBack, onSeeResults }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = usePersistentState('test.scenario', run?.scenario.id ?? '')
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  useEffect(() => {
    listScenarios().then(setScenarios, (e: unknown) => setLoadError(friendlyError(e)))
  }, [])

  const chosen = scenarios?.find((s) => s.id === selected) ?? scenarios?.[0] ?? null
  const shown = run && chosen && run.scenario.id === chosen.id ? run : null
  const broken = shown?.response.report.results.filter((r) => r.status === 'violation').length ?? 0

  async function start() {
    if (!chosen) return
    setRunning(true)
    setRunError(null)
    try {
      onRun({ scenario: chosen, response: await runScenario(spec, chosen.id) })
    } catch (e) {
      setRunError(friendlyError(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="layout">
      <aside className="policy">
        <h1 className="policy__title">Your rules</h1>
        <ol className="rules">
          {spec.rules.map((r, i) => (
            <li key={r.id} className="rules__item rules__item--confirmed">
              <span className="rules__name">
                {i + 1}. {ruleTitle(r)}
              </span>
              <span className="rules__status">Confirmed</span>
            </li>
          ))}
        </ol>
        <button type="button" className="btn btn--link" onClick={onBack}>
          ← Change my rules
        </button>
      </aside>

      <main className="stage">
        <div className="bubble">
          <span className="bubble__avatar" aria-hidden="true">
            H
          </span>
          <p>Pick an AI agent and a problem to throw at it. I’ll check what it did against your rules.</p>
        </div>

        {loadError && (
          <p className="notice notice--error" role="alert">
            {loadError}
          </p>
        )}

        {scenarios && (
          <section className="card" aria-labelledby="pick-title">
            <h2 id="pick-title" className="card__title">
              Test your agent
            </h2>
            <div className="scenarios" role="radiogroup" aria-label="Scenario">
              {scenarios.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  role="radio"
                  aria-checked={s.id === chosen?.id}
                  className={s.id === chosen?.id ? 'scenario scenario--on' : 'scenario'}
                  onClick={() => setSelected(s.id)}
                >
                  <span className="scenario__title">{s.title}</span>
                  <span className="scenario__desc">{s.description}</span>
                </button>
              ))}
            </div>
            <div className="card__actions">
              <button type="button" className="btn btn--primary" onClick={start} disabled={running}>
                {running ? 'Running…' : '▶ Run test'}
              </button>
            </div>
            {runError && (
              <p className="notice notice--error" role="alert">
                {runError}
              </p>
            )}
          </section>
        )}

        {shown && (
          <section className="card" aria-labelledby="ran-title">
            <h2 id="ran-title" className="card__title">
              {broken ? `${broken} rule${broken > 1 ? 's' : ''} broken` : 'All rules held'}
            </h2>
            <p className="card__lead">What the agent did:</p>
            <Timeline events={shown.response.events} />
            <Verdicts results={shown.response.report.results} />
            <div className="card__actions">
              <button type="button" className="btn btn--primary" onClick={onSeeResults}>
                See results →
              </button>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
