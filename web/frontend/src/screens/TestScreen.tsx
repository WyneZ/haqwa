import { useEffect, useState, type ChangeEvent } from 'react'
import { checkEvents, friendlyError, listScenarios, runScenario, summarizeTrace } from '../api/client'
import type { LogEvent, Scenario, Spec } from '../api/types'
import { SpecDownload } from '../components/SpecDownload'
import { Timeline } from '../components/Timeline'
import { Verdicts } from '../components/Verdicts'
import { usePersistentState } from '../lib/persist'
import type { Run } from '../lib/run'
import { HR_NAME, type Source } from '../lib/source'
import { readEventsFile, readHrSample } from '../lib/traceFile'
import { traceTimeline } from '../lib/traceTimeline'
import { verdictKind } from '../lib/verdict'
import { ruleTitle } from '../lib/words'

interface Props {
  spec: Spec
  specYaml: string
  source: Source
  events: LogEvent[] | null
  onTraceLoaded: (source: Source, events: LogEvent[]) => void
  run: Run | null
  onRun: (run: Run) => void
  onBack: () => void
  onSeeResults: () => void
}

const SCENARIO_BADGES: Record<Scenario['kind'], string> = {
  scripted: 'Scripted agent',
  live: 'Live Gemini run · recorded',
  recorded: 'Gemini run · recorded',
}

const SCENARIO_ORDER: Record<Scenario['kind'], number> = {
  live: 0,
  scripted: 1,
  recorded: 2,
}

/**
 * Screen 2 (Test): pick a demo agent + fault, run it, see what it did and core's verdict.
 * The run and the verdict come from the API; this screen only displays them.
 */
export function TestScreen({
  spec,
  specYaml,
  source,
  events,
  onTraceLoaded,
  run,
  onRun,
  onBack,
  onSeeResults,
}: Props) {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = usePersistentState(
    'test.scenario',
    run?.source.kind === 'scenario' ? run.source.scenario.id : '',
  )
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [loadingEvents, setLoadingEvents] = useState(false)

  useEffect(() => {
    if (source.kind === 'shop') {
      listScenarios().then(
        (items) =>
          setScenarios(
            [...items].sort((a, b) => SCENARIO_ORDER[a.kind] - SCENARIO_ORDER[b.kind]),
          ),
        (e: unknown) => setLoadError(friendlyError(e)),
      )
    }
  }, [source.kind])

  const chosen = scenarios?.find((s) => s.id === selected) ?? scenarios?.[0] ?? null
  const shown =
    run &&
    (source.kind === 'trace'
      ? run.source.kind === 'trace'
      : run.source.kind === 'agent' ||
        (run.source.kind === 'scenario' && chosen && run.source.scenario.id === chosen.id))
      ? run
      : null
  const kinds = shown?.response.report.results.map(verdictKind) ?? []
  const broken = kinds.filter((k) => k === 'broken').length
  const untested = kinds.filter((k) => k === 'untested').length

  async function start() {
    if (source.kind === 'shop' && !chosen) return
    if (source.kind === 'trace' && !events) return
    setRunning(true)
    setRunError(null)
    try {
      if (source.kind === 'trace' && events) {
        onRun({
          source: { kind: 'trace', name: source.name, eventCount: events.length },
          response: await checkEvents(spec, events),
        })
      } else if (chosen) {
        onRun({
          source: { kind: 'scenario', scenario: chosen },
          response: await runScenario(spec, chosen.id),
        })
      }
    } catch (e) {
      setRunError(friendlyError(e))
    } finally {
      setRunning(false)
    }
  }

  async function restore(log: LogEvent[], name: string) {
    if (source.kind !== 'trace') return
    setLoadingEvents(true)
    setRunError(null)
    try {
      const summary = await summarizeTrace(log, source.extraEvents)
      onTraceLoaded({ kind: 'trace', name, summary, extraEvents: source.extraEvents }, log)
    } catch (error) {
      setRunError(friendlyError(error))
    } finally {
      setLoadingEvents(false)
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      await restore(await readEventsFile(file), file.name)
    } catch (error) {
      setRunError(error instanceof Error ? error.message : friendlyError(error))
    }
  }

  const traceEvents = shown?.source.kind === 'trace' ? traceTimeline(shown.response) : []

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
        <SpecDownload specYaml={specYaml} />
        <button type="button" className="btn btn--link" onClick={onBack}>
          ← Change my rules
        </button>
      </aside>

      <main className="stage">
        <div className="bubble">
          <span className="bubble__avatar" aria-hidden="true">
            H
          </span>
          <p>
            {source.kind === 'trace'
              ? "I'll check every event in your log against your rules. The checker decides; the AI only explains."
              : 'Pick a run to check. Scripted agents show the classic mistakes; live runs are a real Gemini agent that we recorded.'}
          </p>
        </div>

        {loadError && (
          <p className="notice notice--error" role="alert">
            {loadError}
          </p>
        )}

        {source.kind === 'trace' && (
          <section className="card" aria-labelledby="trace-run-title">
            <h2 id="trace-run-title" className="card__title">
              Check your events
            </h2>
            <p className="card__lead">
              {source.name} · {source.summary.event_count} events
            </p>
            {!events && (
              <div className="trace-restore">
                <p>Please choose your events file again</p>
                <input
                  type="file"
                  accept=".json,application/json"
                  aria-label="Choose events file again"
                  onChange={(event) => void upload(event)}
                />
                {source.name === HR_NAME && (
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={loadingEvents}
                    onClick={() =>
                      void readHrSample()
                        .then((log) => restore(log, HR_NAME))
                        .catch((error: unknown) => setRunError(friendlyError(error)))
                    }
                  >
                    Use HR sample again
                  </button>
                )}
              </div>
            )}
            {events && (
              <button
                type="button"
                className="btn btn--primary"
                disabled={running}
                onClick={() => void start()}
              >
                {running ? 'Checking…' : '▶ Check my events'}
              </button>
            )}
            {runError && <p className="notice notice--error" role="alert">{runError}</p>}
          </section>
        )}

        {source.kind === 'shop' && scenarios && (
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
                  <span className={`scenario__badge scenario__badge--${s.kind}`}>
                    {SCENARIO_BADGES[s.kind]}
                  </span>
                  <span className="scenario__desc">{s.description}</span>
                </button>
              ))}
            </div>
            <div className="card__actions">
              <button type="button" className="btn btn--primary" onClick={() => void start()} disabled={running}>
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
              {broken
                ? `${broken} rule${broken > 1 ? 's' : ''} broken`
                : untested
                  ? 'No rule broken'
                  : 'All rules held'}
            </h2>
            {untested > 0 && (
              <p className="card__lead">
                {untested} rule{untested > 1 ? 's were' : ' was'} not tested: nothing they are
                about happened in this run.
              </p>
            )}
            {shown.source.kind !== 'trace' && (
              <>
                <p className="card__lead">What the agent did:</p>
                <Timeline events={shown.response.events} />
              </>
            )}
            {shown.source.kind === 'trace' && traceEvents.length > 0 && (
              <>
                <p className="card__lead">
                  Showing {traceEvents.length} of {shown.response.events.length} events (only those
                  involved in a broken rule)
                </p>
                <Timeline events={traceEvents} />
              </>
            )}
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
