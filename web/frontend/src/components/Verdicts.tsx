import type { RuleResult } from '../api/types'

/** One line per rule with core's verdict. The web only displays it. */
export function Verdicts({ results }: { results: RuleResult[] }) {
  if (!results.length) return <p className="muted">No rules were checked.</p>
  return (
    <ul className="verdicts">
      {results.map((r) => (
        <li key={r.rule_id} className="verdicts__row">
          <span className={r.status === 'pass' ? 'badge badge--ok' : 'badge badge--bad'}>
            {r.status === 'pass' ? 'Pass' : 'Broken'}
          </span>
          <span>{r.source}</span>
        </li>
      ))}
    </ul>
  )
}
