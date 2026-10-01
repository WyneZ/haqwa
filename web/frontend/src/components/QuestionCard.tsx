import type { Question } from '../api/types'
import { timelineLabels } from '../lib/words'

interface Props {
  question: Question
  index: number // 0-based
  total: number
  noun: string // "order"
  onAnswer: (allowed: boolean) => void
  onBack?: () => void
}

/** One Yes/No card: "If this happens to one order: A -> B -> C. Is this allowed?" */
export function QuestionCard({ question, index, total, noun, onAnswer, onBack }: Props) {
  const labels = timelineLabels(question.timeline)
  return (
    <section className="card" aria-labelledby="q-title">
      <div className="card__meta">
        <span>
          Question {index + 1} of {total}
        </span>
        <span className="dots" aria-hidden="true">
          {Array.from({ length: total }, (_, i) => (
            <span key={i} className={i <= index ? 'dot dot--on' : 'dot'} />
          ))}
        </span>
      </div>

      <p className="card__lead">If this happens to one {noun}:</p>
      <ol className="chips">
        {labels.map((label, i) => (
          <li key={i} className="chips__item">
            {i > 0 && (
              <span className="chips__arrow" aria-hidden="true">
                →
              </span>
            )}
            <span className="chip">{label}</span>
          </li>
        ))}
      </ol>

      <h2 id="q-title" className="card__question">
        Is this allowed?
      </h2>
      <p className="card__context">{question.text}</p>

      <div className="card__actions">
        <button type="button" className="btn btn--yes" onClick={() => onAnswer(true)}>
          Yes, it’s allowed
        </button>
        <button type="button" className="btn btn--no" onClick={() => onAnswer(false)}>
          No, it breaks the rule
        </button>
      </div>

      {onBack && (
        <button type="button" className="btn btn--link" onClick={onBack}>
          ← Previous question
        </button>
      )}
    </section>
  )
}
