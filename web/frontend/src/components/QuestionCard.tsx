import type { Question } from '../api/types'
import { entityCount, timelineLabels } from '../lib/words'

interface Props {
  question: Question
  index: number // 0-based
  total: number
  noun: string // "order"
  per: string // the rule's entity key, e.g. "order_id"
  onAnswer: (allowed: boolean) => void
  onBack?: () => void
  backLabel?: string // default "← Previous question"
}

/**
 * One Yes/No card: "If this happens to one order: A -> B -> C", then the question
 * (`question.text`) as the heading, then Yes / No.
 * When the timeline involves two different orders, the lead says so and each step
 * names its order ("order A", "order B").
 */
export function QuestionCard({
  question,
  index,
  total,
  noun,
  per,
  onAnswer,
  onBack,
  backLabel = '← Previous question',
}: Props) {
  const labels = timelineLabels(question.timeline, per)
  const entities = entityCount(question.timeline, per)
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

      <p className="card__lead">
        {entities > 1
          ? `If this happens to ${entities === 2 ? 'two' : entities} different ${noun}s:`
          : `If this happens to one ${noun}:`}
      </p>
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

      {/* The question itself is the heading: Gemini's decision question, or core's
          plain-English situation + "Is this allowed?" for a confirmation card. */}
      <h2 id="q-title" className="card__question">
        {question.text}
      </h2>

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
          {backLabel}
        </button>
      )}
    </section>
  )
}
