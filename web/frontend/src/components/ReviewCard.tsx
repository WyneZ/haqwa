import type { Question } from '../api/types'
import { timelineLabels } from '../lib/words'

interface Props {
  questions: Question[]
  answers: boolean[]
  busy: boolean
  error: string | null
  mismatches: string[]
  onConfirm: () => void
  onRestart: () => void
}

/** "Here's what you decided" + Confirm. Shown after the last question of a rule. */
export function ReviewCard({ questions, answers, busy, error, mismatches, onConfirm, onRestart }: Props) {
  return (
    <section className="card" aria-labelledby="review-title">
      <h2 id="review-title" className="card__title">
        {questions.length ? 'Here’s what you decided' : 'No questions needed for this rule'}
      </h2>

      {questions.length > 0 && (
        <ul className="summary">
          {questions.map((q, i) => (
            <li key={q.id} className="summary__row">
              <span className={answers[i] ? 'badge badge--ok' : 'badge badge--bad'}>
                {answers[i] ? 'Allowed' : 'Not allowed'}
              </span>
              <span>{timelineLabels(q.timeline).join(' → ')}</span>
            </li>
          ))}
        </ul>
      )}

      {mismatches.length > 0 && (
        <p className="notice notice--warn" role="alert">
          Some answers don’t match how this rule works. Please rewrite the rule or change your
          answers.
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
