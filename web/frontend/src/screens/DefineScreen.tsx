import { useState } from 'react'
import { applyAnswers, clarifyRules, friendlyError } from '../api/client'
import type { ClarifyResult, Rule } from '../api/types'
import { PolicyPanel, type RuleRow } from '../components/PolicyPanel'
import { QuestionCard } from '../components/QuestionCard'
import { ReviewCard } from '../components/ReviewCard'
import { TechDetails } from '../components/TechDetails'
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
 * All meaning changes come from the API (`clarify`, `answers`); this screen only keeps
 * track of where the owner is.
 */
export function DefineScreen() {
  const [text, setText] = useState(DEMO_POLICY)
  const [results, setResults] = useState<ClarifyResult[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [current, setCurrent] = useState<number | null>(null)
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState<boolean[]>([])
  const [confirmed, setConfirmed] = useState<Record<number, Rule>>({})

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [mismatches, setMismatches] = useState<string[]>([])

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
    setAnswers([])
    setMismatches([])
    setSaveError(null)
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
    setAnswers((prev) => [...prev.slice(0, step), allowed])
    setStep((s) => s + 1)
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
                onAnswer={answer}
                onBack={step > 0 ? () => setStep((s) => s - 1) : undefined}
              />
            ) : (
              <ReviewCard
                questions={rule.questions}
                answers={answers}
                busy={saving}
                error={saveError}
                mismatches={mismatches}
                onConfirm={confirm}
                onRestart={resetAnswers}
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
            <button type="button" className="btn btn--primary" disabled>
              Next: test an agent (coming soon)
            </button>
          </section>
        )}
      </main>
    </div>
  )
}
