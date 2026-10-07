import { useState } from 'react'
import {
  applyAnswers,
  clarifyRules,
  friendlyError,
  sealSpec,
  selfTestFailures,
} from '../api/client'
import type { ClarifyResult, Rule } from '../api/types'
import { PolicyPanel, type RuleRow } from '../components/PolicyPanel'
import { QuestionCard } from '../components/QuestionCard'
import { ReviewCard } from '../components/ReviewCard'
import { TechDetails } from '../components/TechDetails'
import { usePersistentState } from '../lib/persist'
import { entityNoun, ruleTitle } from '../lib/words'

const DEMO_POLICY = [
  'A customer must not be charged twice for the same order.',
  'A cancelled order must never be shipped.',
  'A refund must be completed within 24 hours of the request.',
].join('\n')

/** Index of the first supported rule that is not confirmed yet, or null when all are done. */
function nextRule(results: ClarifyResult[], confirmed: Record<number, Rule>): number | null {
  const i = results.findIndex((r, idx) => r.status === 'supported' && !(idx in confirmed))
  return i === -1 ? null : i
}

/**
 * Screen 1 (Define): the AI interviews the policy owner, one question at a time.
 * All meaning changes come from the API (`clarify`, `answers`, `seal`); this screen only keeps
 * track of where the owner is. Progress is saved for this tab, so a refresh keeps the
 * answers and does not call the AI again.
 */
export function DefineScreen({ onDone }: { onDone: (rules: Rule[]) => void }) {
  const [text, setText] = usePersistentState('define.text', DEMO_POLICY)
  const [results, setResults] = usePersistentState<ClarifyResult[] | null>('define.results', null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [current, setCurrent] = usePersistentState<number | null>('define.current', null)
  const [step, setStep] = usePersistentState('define.question', 0)
  const [answers, setAnswers] = usePersistentState<boolean[]>('define.answers', [])
  // Question being re-asked from the review card ("Fix this answer"), or null.
  const [fixing, setFixing] = usePersistentState<number | null>('define.fixing', null)
  const [confirmed, setConfirmed] = usePersistentState<Record<number, Rule>>('define.confirmed', {})

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [mismatches, setMismatches] = useState<string[]>([])

  // Seal: core replays every answer before the owner moves on (C3 endpoint 3).
  const [sealing, setSealing] = useState(false)
  const [sealError, setSealError] = useState<string | null>(null)
  const [redo, setRedo] = useState<number[]>([]) // rules whose answers core rejected

  async function understand() {
    const rules = text.split('\n').map((l) => l.trim()).filter(Boolean)
    setLoading(true)
    setLoadError(null)
    try {
      const res = await clarifyRules(rules)
      setResults(res.results)
      setConfirmed({})
      setCurrent(nextRule(res.results, {}))
      resetAnswers()
    } catch (e) {
      setLoadError(friendlyError(e))
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
    const rules = Object.values(confirmed)
    setSealing(true)
    setSealError(null)
    setRedo([])
    try {
      await sealSpec({ version: 1, rules })
      onDone(rules)
    } catch (e) {
      const failedIds = new Set(selfTestFailures(e).map((f) => f.rule_id))
      const indexes = Object.entries(confirmed)
        .filter(([, r]) => failedIds.has(r.id))
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
  }

  function editRules() {
    setResults(null)
    setCurrent(null)
    setConfirmed({})
    resetAnswers()
  }

  const active = results && current !== null ? results[current] : null
  const rule = active?.status === 'supported' ? active : null

  function answer(allowed: boolean) {
    if (fixing !== null && rule) {
      // Replace only this answer and go straight back to the review card.
      setAnswers((prev) => prev.map((a, i) => (i === fixing ? allowed : a)))
      setMismatches([])
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
    setSaving(true)
    setSaveError(null)
    try {
      const res = await applyAnswers(
        rule.rule,
        rule.questions.map((question, i) => ({ question, allowed: answers[i] })),
      )
      if (res.mismatches.length) {
        setMismatches(res.mismatches)
        return
      }
      const done = { ...confirmed, [current]: res.rule }
      setConfirmed(done)
      setCurrent(nextRule(results, done))
      resetAnswers()
    } catch (e) {
      setSaveError(friendlyError(e))
    } finally {
      setSaving(false)
    }
  }

  const rows: RuleRow[] | null =
    results?.map((r, i) =>
      r.status === 'unsupported'
        ? { title: r.source, status: 'unsupported' }
        : {
            title: ruleTitle(r.rule),
            status: i in confirmed ? 'confirmed' : i === current ? 'asking' : 'waiting',
          },
    ) ?? null

  const unsupported = results?.filter((r) => r.status === 'unsupported') ?? []

  return (
    <div className="layout">
      <PolicyPanel
        text={text}
        onTextChange={setText}
        onSubmit={understand}
        onEdit={editRules}
        busy={loading}
        rows={rows}
      />

      <main className="stage">
        {!results && (
          <div className="empty">
            {loadError ? (
              <p className="notice notice--error" role="alert">
                {loadError}
              </p>
            ) : (
              <p>
                Write your rules on the left. I’ll ask you a few Yes/No questions so each rule
                means exactly what you intend.
              </p>
            )}
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

            <TechDetails rule={rule.rule} />
          </>
        )}

        {results && current === null && (
          <section className="card card--done">
            <h2 className="card__title">✓ Your rules are confirmed</h2>
            <p>Haqwa will check exactly what you decided. Nothing is left to the AI.</p>
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
                      Answer “{ruleTitle(r.rule)}” again
                    </button>
                  ) : null
                })}
              </div>
            )}
            <button
              type="button"
              className="btn btn--primary"
              onClick={finish}
              disabled={sealing || Object.keys(confirmed).length === 0}
            >
              {sealing ? 'Checking your answers…' : 'Next: test an agent →'}
            </button>
          </section>
        )}
      </main>
    </div>
  )
}
