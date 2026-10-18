import { useState } from 'react'
import type { LogEvent, SpecRule, Spec } from './api/types'
import { Header } from './components/Header'
import { clearSaved, usePersistentState } from './lib/persist'
import type { Run } from './lib/run'
import type { Source } from './lib/source'
import { DefineScreen } from './screens/DefineScreen'
import { ResultsScreen } from './screens/ResultsScreen'
import { TestScreen } from './screens/TestScreen'

type Step = 'policy' | 'evidence' | 'meaning' | 'test' | 'results'
const STEPS: Step[] = ['policy', 'evidence', 'meaning', 'test', 'results']

/**
 * Five stages, no router (decision 2026-10-05). The wizard state is saved in
 * sessionStorage, so a refresh keeps the owner where they were.
 * "Start over" clears it and remounts everything with a new key.
 */
export default function App() {
  const [session, setSession] = useState(0)
  return (
    <Wizard
      key={session}
      onStartOver={() => {
        clearSaved()
        setSession((s) => s + 1)
      }}
    />
  )
}

function Wizard({ onStartOver }: { onStartOver: () => void }) {
  const [step, setStep] = usePersistentState<Step>('step', 'policy')
  const [spec, setSpec] = usePersistentState<Spec | null>('spec', null)
  const [specYaml, setSpecYaml] = usePersistentState<string | null>('specYaml', null)
  const [savedRun, setSavedRun] = usePersistentState<Run | null>('run', null)
  const [traceRun, setTraceRun] = useState<Run | null>(null)
  const [source, setSource] = usePersistentState<Source>('source', { kind: 'shop' })
  const [events, setEvents] = useState<LogEvent[] | null>(null)
  const run = source.kind === 'shop' ? savedRun : traceRun

  function setRun(next: Run | null) {
    if (next?.source.kind === 'trace') {
      setTraceRun(next)
      setSavedRun(null)
    } else {
      setSavedRun(next)
      setTraceRun(null)
    }
  }

  function changeSource(next: Source, log: LogEvent[] | null) {
    setSource(next)
    setEvents(log)
    setSpec(null)
    setSpecYaml(null)
    setRun(null)
  }

  // Never show a screen without its data (e.g. saved data from an older version).
  let view: Step = step
  if ((step === 'test' || step === 'results') && (!spec || !specYaml)) view = 'policy'
  if (view === 'results' && !run) view = 'test'

  function rulesConfirmed(rules: SpecRule[], yaml: string) {
    setSpec({ version: 2, rules })
    setSpecYaml(yaml)
    setRun(null)
    setStep('test')
  }

  return (
    <div className="app">
      <Header active={STEPS.indexOf(view)} onStartOver={onStartOver} />
      {(view === 'policy' || view === 'evidence' || view === 'meaning') && (
        <DefineScreen
          phase={view}
          onPhaseChange={setStep}
          source={source}
          onSourceChange={changeSource}
          onDone={rulesConfirmed}
        />
      )}
      {view === 'test' && spec && specYaml && (
        <TestScreen
          spec={spec}
          specYaml={specYaml}
          source={source}
          events={events}
          onTraceLoaded={(next, log) => {
            setSource(next)
            setEvents(log)
            setRun(null)
          }}
          run={run}
          onRun={setRun}
          onBack={() => setStep('meaning')}
          onSeeResults={() => setStep('results')}
        />
      )}
      {view === 'results' && spec && specYaml && run && (
        <ResultsScreen
          spec={spec}
          specYaml={specYaml}
          run={run}
          onRun={setRun}
          onBack={() => setStep('test')}
        />
      )}
    </div>
  )
}
