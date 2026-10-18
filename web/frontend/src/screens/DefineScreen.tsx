import { useRef, useState, type ChangeEvent } from 'react'
import {
  applyAnswers,
  clarifyRules,
  friendlyError,
  sealSpec,
  selfTestFailures,
  summarizeTrace,
} from '../api/client'
import type { AnswersResponse, ClarifyResult, LogEvent, SpecRule, TraceVocabulary } from '../api/types'
import { PolicyPanel, type RuleRow } from '../components/PolicyPanel'
import { PolicyUpload } from '../components/PolicyUpload'
import { QuestionCard } from '../components/QuestionCard'
import { ReviewCard } from '../components/ReviewCard'
import { TechDetails } from '../components/TechDetails'
import { TraceSummaryCard } from '../components/TraceSummaryCard'
import { LiveVocabularyForm } from '../components/LiveVocabularyForm'
import { usePersistentState } from '../lib/persist'
import { toSpecRule } from '../lib/specRule'
import { HR_NAME, HR_RULES, type Source } from '../lib/source'
import { readEventsFile, readHrSample } from '../lib/traceFile'
import { entityNoun } from '../lib/words'

const DEMO_POLICY = [
  'A customer must not be charged twice for the same order.',
  'A cancelled order must never be shipped.',
  'A refund must be completed within 24 hours of the request.',
].join('\n')

/** Index of the first supported rule that is not confirmed yet, or null when all are done. */
function nextRule(results: ClarifyResult[], confirmed: Record<number, AnswersResponse>): number | null {
  const i = results.findIndex((r, idx) => r.status === 'supported' && !(idx in confirmed))
  return i === -1 ? null : i
}

/**
 * Policy, evidence, and meaning stages. The AI interviews the policy owner one question at a time.
 * All meaning changes come from the API (`clarify`, `answers`, `seal`); this screen only keeps
 * track of where the owner is. Progress is saved for this tab, so a refresh keeps the
 * answers and does not call the AI again.
 */
interface Props {
  phase: 'policy' | 'evidence' | 'meaning'
  onPhaseChange: (phase: 'policy' | 'evidence' | 'meaning') => void
  source: Source
  onSourceChange: (source: Source, events: LogEvent[] | null) => void
  onDone: (rules: SpecRule[], specYaml: string) => void
}

export function DefineScreen({ phase, onPhaseChange, source, onSourceChange, onDone }: Props) {
  const [choice, setChoice] = usePersistentState<'upload' | 'live' | 'demo' | null>(
    'evidence.choice', source.kind === 'trace' ? (source.name === HR_NAME ? 'demo' : 'upload') : source.kind === 'live' ? 'live' : null,
  )
  const [demo, setDemo] = usePersistentState<'shop' | 'hr'>('evidence.demo', source.kind === 'trace' && source.name === HR_NAME ? 'hr' : 'shop')
  const [sourceBusy, setSourceBusy] = useState(false)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const choiceRequest = useRef(0)
  const [text, setText] = usePersistentState('define.text', '')
  const [results, setResults] = usePersistentState<ClarifyResult[] | null>('define.results', null)
  const [interviewVocabulary, setInterviewVocabulary] = usePersistentState<TraceVocabulary | null>('define.vocabulary', null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [current, setCurrent] = usePersistentState<number | null>('define.current', null)
  const [step, setStep] = usePersistentState('define.question', 0)
  const [answers, setAnswers] = usePersistentState<boolean[]>('define.answers', [])
  // Question being re-asked from the review card ("Fix this answer"), or null.
  const [fixing, setFixing] = usePersistentState<number | null>('define.fixing', null)
  const [confirmed, setConfirmed] = usePersistentState<Record<number, AnswersResponse>>('define.confirmed', {})
  const [answerHistory, setAnswerHistory] = usePersistentState<Record<number, boolean[]>>('define.answerHistory', {})

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [mismatches, setMismatches] = useState<string[]>([])

  // Seal: core replays every answer before the owner moves on (C3 endpoint 3).
  const [sealing, setSealing] = useState(false)
  const [sealError, setSealError] = useState<string | null>(null)
  const [redo, setRedo] = useState<number[]>([]) // rules whose answers core rejected

  async function understand() {
    const requestId = choiceRequest.current
    const rules = text.split('\n').map((l) => l.trim()).filter(Boolean)
    const vocabulary = source.kind === 'trace'
      ? source.summary.vocabulary
      : source.kind === 'live' ? source.vocabulary : null
    setLoading(true)
    setLoadError(null)
    try {
      const res = await clarifyRules(
        rules,
        vocabulary ?? undefined,
      )
      if (requestId !== choiceRequest.current) return
      setResults(res.results)
      // Test may later load a different trace; answers must retain this interview's names.
      setInterviewVocabulary(vocabulary)
      setConfirmed({})
      setAnswerHistory({})
      setCurrent(nextRule(res.results, {}))
      resetAnswers()
    } catch (e) {
      if (requestId === choiceRequest.current) setLoadError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  function resetAnswers() {
    setStep(0)
    setFixing(null)
    setAnswers([])
    setMismatches([])
    setSaveError(null)
  }

  /**
   * Ask core to compile the confirmed rules and replay every owner answer (self-test).
   * Only a spec core accepts goes to the Test screen; otherwise the owner re-answers the
   * rules core named, so a bad spec can never reach a test run.
   */
  async function finish() {
    const requestId = choiceRequest.current
    const rules = Object.values(confirmed).map(result => toSpecRule(result.rule, result.confirmed_examples))
    setSealing(true)
    setSealError(null)
    setRedo([])
    try {
      const sealed = await sealSpec({ version: 2, rules }, interviewVocabulary ?? undefined)
      if (requestId !== choiceRequest.current) return
      onDone(rules, sealed.spec_yaml)
    } catch (e) {
      if (requestId !== choiceRequest.current) return
      const failedIds = new Set(selfTestFailures(e).map((f) => f.rule_id))
      const indexes = Object.entries(confirmed)
        .filter(([, r]) => failedIds.has(r.rule.id))
        .map(([i]) => Number(i))
      setRedo(indexes)
      setSealError(friendlyError(e))
    } finally {
      setSealing(false)
    }
  }

  /** Re-open one confirmed rule so the owner answers its questions again. */
  function answerAgain(index: number) {
    const rest = { ...confirmed }
    delete rest[index]
    setConfirmed(rest)
    setCurrent(index)
    setRedo([])
    setSealError(null)
    resetAnswers()
    const saved = answerHistory[index]
    const result = results?.[index]
    if (saved && result?.status === 'supported' && saved.length === result.questions.length) {
      setAnswers(saved)
      setStep(result.questions.length)
    }
  }

  function editRules() {
    setResults(null)
    setInterviewVocabulary(null)
    setCurrent(null)
    setConfirmed({})
    setAnswerHistory({})
    resetAnswers()
  }

  function clearInterview() {
    setResults(null)
    setInterviewVocabulary(null)
    setCurrent(null)
    setConfirmed({})
    setAnswerHistory({})
    resetAnswers()
    setLoadError(null)
    setSealError(null)
    setRedo([])
  }

  async function loadTrace(name: string, log: LogEvent[], extraEvents: string[], requestId: number) {
    const summary = await summarizeTrace(log, extraEvents)
    if (requestId !== choiceRequest.current) return
    onSourceChange({ kind: 'trace', name, summary, extraEvents }, log)
  }

  function choose(next: 'upload' | 'live' | 'demo') {
    const requestId = ++choiceRequest.current
    setChoice(next)
    setSourceBusy(false)
    setSourceError(null)
    clearInterview()
    onSourceChange({ kind: 'shop' }, null)
    if (next === 'demo' && demo === 'hr') void chooseDemo('hr', requestId)
  }

  async function chooseDemo(next: 'shop' | 'hr', existingRequest?: number) {
    const requestId = existingRequest ?? ++choiceRequest.current
    setDemo(next)
    setSourceBusy(false)
    setSourceError(null)
    clearInterview()
    onSourceChange({ kind: 'shop' }, null)
    if (next === 'shop') return
    setSourceBusy(true)
    try {
      await loadTrace(HR_NAME, await readHrSample(), ['payroll_run'], requestId)
    } catch (error) {
      if (requestId === choiceRequest.current) {
        setSourceError(error instanceof Error ? error.message : friendlyError(error))
      }
    } finally {
      if (requestId === choiceRequest.current) setSourceBusy(false)
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const requestId = ++choiceRequest.current
    setSourceBusy(true)
    setSourceError(null)
    clearInterview()
    onSourceChange({ kind: 'shop' }, null)
    try {
      await loadTrace(file.name, await readEventsFile(file), [], requestId)
    } catch (error) {
      if (requestId === choiceRequest.current) {
        setSourceError(error instanceof Error ? error.message : friendlyError(error))
      }
    } finally {
      if (requestId === choiceRequest.current) setSourceBusy(false)
    }
  }

  const active = results && current !== null ? results[current] : null
  const rule = active?.status === 'supported' ? active : null

  function answer(allowed: boolean) {
    if (fixing !== null && rule) {
      // Replace only this answer and go straight back to the review card.
      setAnswers((prev) => prev.map((a, i) => (i === fixing ? allowed : a)))
      const question = rule.questions[fixing]
      if (question.expected_violation === !allowed) {
        setMismatches((prev) => prev.filter((m) => m.split(':')[0].trim() !== question.id))
      }
      setFixing(null)
      setStep(rule.questions.length)
      return
    }
    setAnswers((prev) => [...prev.slice(0, step), allowed])
    setStep((s) => s + 1)
  }

  /** "Fix this answer" on the review card: re-ask one question. */
  function fixAnswer(index: number) {
    setFixing(index)
    setStep(index)
    setSaveError(null)
  }

  /** Leave a fix without changing the answer. */
  function cancelFix() {
    if (!rule) return
    setFixing(null)
    setStep(rule.questions.length)
  }

  async function confirm() {
    if (!rule || current === null || !results) return
    const requestId = choiceRequest.current
    setSaving(true)
    setSaveError(null)
    try {
      const res = await applyAnswers(
        rule.rule,
        rule.questions.map((question, i) => ({ question, allowed: answers[i] })),
        interviewVocabulary ?? undefined,
      )
      if (requestId !== choiceRequest.current) return
      if (res.mismatches.length) {
        setMismatches(res.mismatches)
        return
      }
      const done = { ...confirmed, [current]: res }
      setAnswerHistory({ ...answerHistory, [current]: [...answers] })
      setConfirmed(done)
      setCurrent(nextRule(results, done))
      resetAnswers()
    } catch (e) {
      if (requestId === choiceRequest.current) setSaveError(friendlyError(e))
    } finally {
      setSaving(false)
    }
  }

  const rows: RuleRow[] | null =
    results?.map((r, i) =>
      r.status === 'unsupported'
        ? { title: r.source, status: 'unsupported' }
        : {
            title: r.source,
            status: i in confirmed ? 'confirmed' : i === current ? 'asking' : 'waiting',
          },
    ) ?? null

  const unsupported = results?.filter((r) => r.status === 'unsupported') ?? []
  const confirmedCount = Object.keys(confirmed).length

  if (phase === 'policy') {
    return (
      <main className="layout layout--policy">
        <PolicyPanel
          text={text}
          onTextChange={setText}
          onSubmit={() => onPhaseChange('evidence')}
          onEdit={editRules}
          busy={false}
          rows={null}
          submitLabel="Next: choose evidence →"
          upload={<PolicyUpload disabled={false} onUse={(rules) => setText(rules.join('\n'))} />}
        />
        <div className="policy-samples">
          <p>Or start from a sample policy:</p>
          <button type="button" className="btn btn--ghost" onClick={() => setText(DEMO_POLICY)}>
            Online shop policy
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setText(HR_RULES)}>
            HR leave policy
          </button>
        </div>
      </main>
    )
  }

  if (phase === 'evidence') {
    return (
      <main className="layout layout--evidence">
        <section className="card source-picker" aria-labelledby="source-title">
          <h1 id="source-title" className="card__title">Choose evidence for your policy</h1>
          <div className="evidence-choices" role="group" aria-label="Evidence choices">
            <button type="button" className={`evidence-card${choice === 'upload' ? ' evidence-card--selected' : ''}`} aria-pressed={choice === 'upload'} onClick={() => choose('upload')}>
              <span className="evidence-card__letter">A</span><strong>Upload an event log (JSON)</strong>
              <span>Use events your agent already recorded.</span>
            </button>
            <button type="button" className={`evidence-card${choice === 'live' ? ' evidence-card--selected' : ''}`} aria-pressed={choice === 'live'} onClick={() => choose('live')}>
              <span className="evidence-card__letter">B</span><strong>Connect my agent (live)</strong>
              <span>Name the events your agent will send while you test.</span>
            </button>
            <button type="button" className={`evidence-card${choice === 'demo' ? ' evidence-card--selected' : ''}`} aria-pressed={choice === 'demo'} onClick={() => choose('demo')}>
              <span className="evidence-card__letter">C</span><strong>Try a demo</strong>
              <span>Explore with Online shop or HR events.</span>
            </button>
          </div>
          {choice === 'upload' && (
            <div className="evidence-detail">
              <input type="file" accept=".json,application/json" aria-label="Choose events file" onChange={(event) => void upload(event)} />
              <details>
                <summary>Event JSON format</summary>
                <code>{'[{"event": "leave_requested", "ts": "2026-09-01T09:00:00Z", "data": {"leave_id": "L-1"}}]'}</code>
              </details>
              {source.kind === 'trace' && <TraceSummaryCard summary={source.summary} />}
            </div>
          )}
          {choice === 'live' && (
            <div className="evidence-detail">
              <LiveVocabularyForm policy={text} onUse={(vocabulary, suggestedEvents) => {
                ++choiceRequest.current
                clearInterview()
                onSourceChange({ kind: 'live', vocabulary, ...(suggestedEvents ? { suggestedEvents } : {}) }, null)
                onPhaseChange('meaning')
              }} />
            </div>
          )}
          {choice === 'demo' && (
            <div className="evidence-detail">
              <p>Demo agents only know the demo events; use A or B for your own policy.</p>
              <div className="demo-options" role="group" aria-label="Demo events">
                <button type="button" className={`btn ${demo === 'shop' ? 'btn--primary' : 'btn--ghost'}`} aria-pressed={demo === 'shop'} onClick={() => void chooseDemo('shop')}>Online shop</button>
                <button type="button" className={`btn ${demo === 'hr' ? 'btn--primary' : 'btn--ghost'}`} aria-pressed={demo === 'hr'} onClick={() => void chooseDemo('hr')}>HR</button>
              </div>
              <button type="button" className="btn btn--ghost" onClick={() => { setText(demo === 'shop' ? DEMO_POLICY : HR_RULES); clearInterview(); onPhaseChange('policy') }}>Use the demo policy</button>
              {demo === 'hr' && source.kind === 'trace' && <TraceSummaryCard summary={source.summary} />}
            </div>
          )}
          {sourceBusy && <p className="card__lead" role="status">Reading events…</p>}
          {sourceError && <p className="notice notice--error" role="alert">{sourceError}</p>}
          <div className="upload__actions">
            <button type="button" className="btn btn--link" onClick={() => { editRules(); onPhaseChange('policy') }}>
              ← Edit policy
            </button>
            {choice !== 'live' && <button type="button" className="btn btn--primary" disabled={sourceBusy || !choice || (choice === 'upload' && source.kind !== 'trace') || (choice === 'demo' && demo === 'hr' && source.kind !== 'trace')} onClick={() => onPhaseChange('meaning')}>Next: understand policy →</button>}
          </div>
        </section>
      </main>
    )
  }

  return (
    <div className="layout layout--meaning">
      <PolicyPanel
        text={text}
        onTextChange={setText}
        onSubmit={understand}
        onEdit={() => { editRules(); onPhaseChange('policy') }}
        busy={loading || saving || sealing}
        onRedo={answerAgain}
        rows={rows ?? []}
      />

      <main className="stage stage--interview" aria-busy={loading}>
        <button type="button" className="btn btn--link" onClick={() => onPhaseChange('evidence')}>
          ← Change evidence
        </button>
        {source.kind === 'trace' && <TraceSummaryCard summary={source.summary} />}
        {!results && (
          <div className="empty">
            {loadError ? (
              <p className="notice notice--error" role="alert">
                {loadError}
              </p>
            ) : (
              <div className="bubble">
                <span className="bubble__avatar" aria-hidden="true">
                  H
                </span>
                <p>
                  I’ll ask a few Yes/No questions so each rule means exactly what you intend.
                </p>
              </div>
            )}
            <button type="button" className="btn btn--primary" onClick={() => void understand()} disabled={loading}>
              {loading ? 'Reading your rules…' : 'Understand my rules'}
            </button>
          </div>
        )}

        {rule && (
          <>
            <div className="bubble">
              <span className="bubble__avatar" aria-hidden="true">
                H
              </span>
              <p>
                For <b>“{rule.source}”</b>, I need you to decide{' '}
                {rule.questions.length === 1 ? 'one case' : 'a few cases'}.
              </p>
            </div>

            <p className="notice meaning" aria-label="Haqwa understood">
              <strong>Haqwa understood:</strong> {rule.meaning}
            </p>

            {step < rule.questions.length ? (
              <QuestionCard
                key={`${current}-${step}`}
                question={rule.questions[step]}
                index={step}
                total={rule.questions.length}
                noun={entityNoun(rule.rule.per)}
                per={rule.rule.per}
                onAnswer={answer}
                onBack={
                  fixing !== null ? cancelFix : step > 0 ? () => setStep((s) => s - 1) : undefined
                }
                backLabel={fixing !== null ? '← Back to my answers' : undefined}
              />
            ) : (
              <ReviewCard
                questions={rule.questions}
                answers={answers}
                busy={saving}
                error={saveError}
                mismatches={mismatches}
                per={rule.rule.per}
                onConfirm={confirm}
                onRestart={resetAnswers}
                onFix={fixAnswer}
              />
            )}

            <TechDetails rule={rule.rule} meaning={rule.meaning} />
          </>
        )}

        {results && current === null && (
          <section className="card card--done">
            <h2 className="card__title">
              {confirmedCount > 0 ? '✓ Supported rules confirmed' : 'No rules can be checked yet'}
            </h2>
            <p>
              {confirmedCount > 0
                ? unsupported.length > 0
                  ? 'Haqwa will check your confirmed rules. The rules listed below will not be checked.'
                  : 'Haqwa will check the rules you confirmed.'
                : source.kind === 'shop'
                  ? 'The online shop demo only knows its existing events. Choose A or B to check your own policy.'
                  : source.kind === 'live'
                    ? 'The event names you listed do not provide a checkable rule. Edit your policy or change the event names.'
                    : 'The uploaded events do not provide a checkable rule. Edit your policy or upload a trace with the events it describes.'}
            </p>
            {confirmedCount > 0 && (
              <ol className="confirmed">
                {Object.entries(confirmed).map(([index, result]) => (
                  <li key={index} className="confirmed__rule">
                    <p className="confirmed__source">“{results[Number(index)].source}”</p>
                    <p className="notice meaning">
                      <strong>Haqwa will check:</strong> {result.meaning}
                    </p>
                    <TechDetails
                      rule={result.rule}
                      meaning={result.meaning}
                      confirmedExamples={result.confirmed_examples}
                    />
                  </li>
                ))}
              </ol>
            )}
            {unsupported.length > 0 && (
              <div className="notice notice--warn">
                <p>These rules can’t be checked yet:</p>
                <ul>
                  {unsupported.map((r) => (
                    <li key={r.source}>
                      “{r.source}” — {r.status === 'unsupported' ? r.reason : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {sealError && (
              <div className="notice notice--error" role="alert">
                <p>{sealError}</p>
                {redo.map((i) => {
                  const r = results[i]
                  return r.status === 'supported' ? (
                    <button
                      key={i}
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => answerAgain(i)}
                    >
                      Answer “{r.source}” again
                    </button>
                  ) : null
                })}
              </div>
            )}
            <button
              type="button"
              className="btn btn--primary"
              onClick={finish}
              disabled={sealing || confirmedCount === 0}
            >
              {sealing ? 'Checking your answers…' : 'Next: test an agent →'}
            </button>
          </section>
        )}
      </main>
    </div>
  )
}
