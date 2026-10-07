import type { Question } from '../api/types'
import { timelineLabels } from '../lib/words'

interface Props {
  questions: Question[]
  answers: boolean[]
  busy: boolean
  error: string | null
  mismatches: string[] // e.g. "c3: owner answered the opposite of 'allowed'"
  per: string // the rule's entity key, e.g. "order_id"
  onConfirm: () => void
  onRestart: () => void
  onFix: (index: number) => void // re-ask one question, keep the other answers
}

/** The question ids named in `mismatches` ("c3: …" -> "c3"). */
function mismatchIds(mismatches: string[]): Set<string> {
  return new Set(mismatches.map((m) => m.split(':')[0].trim()))
}

/**
 * "Here's what you decided" + Confirm. Shown after the last question of a rule.
 * Answers that disagree with how the rule works are highlighted one by one, each with
 * "Fix this answer", which re-asks only that card and keeps the other answers.
 */
export function ReviewCard({
  questions,
  answers,
  busy,
  error,
  mismatches,
  per,
  onConfirm,
  onRestart,
  onFix,
}: Props) {
  const wrong = mismatchIds(mismatches)
  return (
    <section className="card" aria-labelledby="review-title">
      <h2 id="review-title" className="card__title">
        {questions.length ? 'Here’s what you decided' : 'No questions needed for this rule'}
      </h2>

      {questions.length > 0 && (
        <ul className="summary">
          {questions.map((q, i) => (
            <li
              key={q.id}
              className={wrong.has(q.id) ? 'summary__row summary__row--warn' : 'summary__row'}
            >
              <span className={answers[i] ? 'badge badge--ok' : 'badge badge--bad'}>
                {answers[i] ? 'Allowed' : 'Not allowed'}
              </span>
              <span className="summary__text">
                {timelineLabels(q.timeline, per).join(' → ')}
                {wrong.has(q.id) && q.expected_violation !== undefined && (
                  <>
                    <span className="summary__hint">
                      You said “{answers[i] ? 'Allowed' : 'Not allowed'}”, but as the rule is
                      written this is {q.expected_violation ? 'not allowed' : 'allowed'}.
                    </span>
                    <button
                      type="button"
                      className="btn btn--link"
                      onClick={() => onFix(i)}
                      disabled={busy}
                    >
                      Fix this answer
                    </button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {mismatches.length > 0 && (
        <p className="notice notice--warn" role="alert">
          {wrong.size === 1 ? 'One answer doesn’t' : 'Some answers don’t'} match how this rule
          works (highlighted above). Fix that answer, or rewrite the rule if it says
          something different from what you mean.
        </p>
      )}
      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      <div className="card__actions">
        <button type="button" className="btn btn--primary" onClick={onConfirm} disabled={busy}>
          {busy ? 'Saving…' : 'Confirm this rule'}
        </button>
        {questions.length > 0 && (
          <button type="button" className="btn btn--ghost" onClick={onRestart} disabled={busy}>
            Change my answers
          </button>
        )}
      </div>
    </section>
  )
}
