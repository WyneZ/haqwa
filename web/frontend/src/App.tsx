import { useState } from 'react'
import type { Rule, Spec } from './api/types'
import { Header } from './components/Header'
import { clearSaved, usePersistentState } from './lib/persist'
import type { Run } from './lib/run'
import { DefineScreen } from './screens/DefineScreen'
import { ResultsScreen } from './screens/ResultsScreen'
import { TestScreen } from './screens/TestScreen'

type Step = 'define' | 'test' | 'results'

/**
 * Three screens, no router (decision 2026-10-05). The wizard state is saved in
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
  const [step, setStep] = usePersistentState<Step>('step', 'define')
  const [spec, setSpec] = usePersistentState<Spec | null>('spec', null)
  const [run, setRun] = usePersistentState<Run | null>('run', null)

  // Never show a screen without its data (e.g. saved data from an older version).
  let view: Step = 'define'
  if (spec && step !== 'define') view = step === 'results' && run ? 'results' : 'test'

  function rulesConfirmed(rules: Rule[]) {
    setSpec({ version: 1, rules })
    setRun(null)
    setStep('test')
  }

  return (
    <div className="app">
      <Header active={['define', 'test', 'results'].indexOf(view)} onStartOver={onStartOver} />
      {view === 'define' && <DefineScreen onDone={rulesConfirmed} />}
      {view === 'test' && spec && (
        <TestScreen
          spec={spec}
          run={run}
          onRun={setRun}
          onBack={() => setStep('define')}
          onSeeResults={() => setStep('results')}
        />
      )}
      {view === 'results' && spec && run && (
        <ResultsScreen spec={spec} run={run} onRun={setRun} onBack={() => setStep('test')} />
      )}
    </div>
  )
}
