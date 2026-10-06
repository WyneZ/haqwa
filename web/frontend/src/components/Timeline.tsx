import type { LogEvent } from '../api/types'
import { timelineLabels } from '../lib/words'

interface Props {
  events: LogEvent[]
  offendingIndex?: number // marks the event that broke the rule (from core)
}

/**
 * What happened, oldest first, in plain words. Numbered instead of timed: the demo
 * events share one timestamp, so the order is the information.
 */
export function Timeline({ events, offendingIndex }: Props) {
  const labels = timelineLabels(events)
  return (
    <ol className="timeline">
      {labels.map((label, i) => (
        <li
          key={i}
          className={i === offendingIndex ? 'timeline__item timeline__item--bad' : 'timeline__item'}
        >
          <span className="timeline__n">{i === offendingIndex ? '✖' : i + 1}</span>
          <span>{label}</span>
          {i === offendingIndex && <span className="timeline__note">this broke the rule</span>}
        </li>
      ))}
    </ol>
  )
}
