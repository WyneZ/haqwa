import type { TraceSummary } from '../api/types'
import { humanize } from '../lib/words'

function dateLabel(value: string | null, year = true): string {
  return value
    ? new Intl.DateTimeFormat('en-GB', {
        day: 'numeric',
        month: 'short',
        ...(year ? { year: 'numeric' } : {}),
        timeZone: 'UTC',
      }).format(new Date(value))
    : 'unknown date'
}

export function TraceSummaryCard({ summary }: { summary: TraceSummary }) {
  const kindCount = Object.keys(summary.event_counts).length
  const sameYear = summary.first_ts?.slice(0, 4) === summary.last_ts?.slice(0, 4)
  return (
    <section className="card trace-summary" aria-label="Events summary">
      <h2 className="card__title card__title--small">Your events</h2>
      <p className="card__lead">
        {summary.event_count} events · {kindCount} kinds · {dateLabel(summary.first_ts, !sameYear)} –{' '}
        {dateLabel(summary.last_ts)}
      </p>
      <div className="trace-summary__chips">
        {summary.vocabulary.events.map((name) => {
          const count = summary.event_counts[name] ?? 0
          return (
            <span key={name} className={`trace-chip${count ? '' : ' trace-chip--muted'}`}>
              {humanize(name)} · {count ? count : 'not in this log'}
            </span>
          )
        })}
      </div>
      {summary.entity_candidates.length > 0 && (
        <p className="card__lead">
          Grouped by:{' '}
          {summary.entity_candidates
            .slice()
            .reverse()
            .map((name) => name.replace(/_/g, ' '))
            .join(', ')}
        </p>
      )}
    </section>
  )
}
