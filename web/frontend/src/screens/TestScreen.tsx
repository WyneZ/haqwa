import { useEffect, useState, type ChangeEvent } from 'react'
import { checkEvents, friendlyError, listScenarios, runScenario, summarizeTrace } from '../api/client'
import type { LogEvent, Scenario, Spec } from '../api/types'
import { AgentConnectCard } from '../components/AgentConnectCard'
import { SpecDownload } from '../components/SpecDownload'
import { Timeline } from '../components/Timeline'
import { Verdicts } from '../components/Verdicts'
import { usePersistentState } from '../lib/persist'
import type { Run } from '../lib/run'
import { HR_NAME, type Source } from '../lib/source'
import { readEventsFile, readHrSample } from '../lib/traceFile'
import { traceTimeline } from '../lib/traceTimeline'
import { verdictKind } from '../lib/verdict'

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

/** Picker sections, in this order. A kind the API adds later still shows, under "Other runs". */
const SCENARIO_GROUPS: { kind: Scenario['kind']; title: string }[] = [
  { kind: 'live', title: 'Real Gemini agent, recorded over MCP' },
  { kind: 'scripted', title: 'Scripted agents: the classic mistake and its fix' },
  { kind: 'recorded', title: 'Earlier recorded Gemini runs' },
]

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
    <div className="layout layout--test">
      <aside className="policy">
        <h1 className="policy__title">Your rules</h1>
        <ol className="rules">
          {spec.rules.map((r, i) => (
            <li key={r.id} className="rules__item rules__item--confirmed">
              <span className="rules__name">
                {i + 1}. {r.source}
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

      <main className="stage" aria-busy={running || loadingEvents}>
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

        {source.kind === 'shop' && !scenarios && !loadError && (
          <p className="notice notice--loading" role="status">
            Loading demo runs…
          </p>
        )}

        {source.kind === 'trace' && (
          <section className="card test-picker" aria-labelledby="trace-run-title" aria-busy={running}>
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
          <section className="card test-picker" aria-labelledby="pick-title" aria-busy={running}>
            <h2 id="pick-title" className="card__title">
              Test your agent
            </h2>
            <p className="card__lead">
              Pick a run below, or{' '}
              <a href="#agent-connect-title">connect your own MCP agent ↓</a>
            </p>
            <div className="scenario-groups" role="radiogroup" aria-label="Scenario">
              {[
                ...SCENARIO_GROUPS,
                { kind: null, title: 'Other runs' } as const,
              ].map((group) => {
                const items = scenarios.filter((s) =>
                  group.kind === null
                    ? !SCENARIO_GROUPS.some((g) => g.kind === s.kind)
                    : s.kind === group.kind,
                )
                if (items.length === 0) return null
                // Runs of one kind often share a description: say it once for the section.
                const shared =
                  items.length > 1 && items.every((s) => s.description === items[0].description)
                    ? items[0].description
                    : null
                return (
                  <div key={group.title} className="scenario-group">
                    <h3 className="scenario-group__title">{group.title}</h3>
                    {shared && <p className="scenario-group__note">{shared}</p>}
                    <div className="scenarios">
                      {items.map((s) => (
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
                            {SCENARIO_BADGES[s.kind] ?? 'Demo run'}
                          </span>
                          {!shared && <span className="scenario__desc">{s.description}</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}
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
          <section className="card run-preview" aria-labelledby="ran-title">
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
                  Showing {traceEvents.length} of {shown.response.events.length} events: the events
                  leading up to each broken rule
                </p>
                <Timeline events={traceEvents} repeats={false} />
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

        {source.kind === 'shop' && <AgentConnectCard spec={spec} onRun={onRun} />}
      </main>
    </div>
  )
}
