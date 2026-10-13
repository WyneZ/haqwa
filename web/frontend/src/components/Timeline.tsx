import type { LogEvent } from '../api/types'
import { eventTimes, timelineLabels } from '../lib/words'

interface Props {
  events: LogEvent[]
  offendingIndex?: number // marks the event that broke the rule (from core)
  /** false for lists that mix entities (an uploaded log): never label a repeat "again". */
  repeats?: boolean
}

/**
 * What happened, oldest first, in plain words. Numbered; the UTC time is added only when
 * the events span more than a minute (the demo shop events share one timestamp, so there
 * the order is the information).
 */
export function Timeline({ events, offendingIndex, repeats = true }: Props) {
  const labels = timelineLabels(events, undefined, { repeats })
  const times = eventTimes(events)
  return (
    <ol className="timeline">
      {labels.map((label, i) => (
        <li
          key={i}
          className={i === offendingIndex ? 'timeline__item timeline__item--bad' : 'timeline__item'}
        >
          <span className="timeline__n">{i === offendingIndex ? '✖' : i + 1}</span>
          <span>{label}</span>
          {times && (
            <time className="timeline__time" dateTime={events[i].ts}>
              {times[i]}
            </time>
          )}
          {i === offendingIndex && <span className="timeline__note">this broke the rule</span>}
        </li>
      ))}
    </ol>
  )
}
