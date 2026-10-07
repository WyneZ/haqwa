import type { RuleResult } from '../api/types'
import { verdictKind } from '../lib/verdict'

const BADGE = {
  broken: { className: 'badge badge--bad', label: 'Broken' },
  pass: { className: 'badge badge--ok', label: 'Pass' },
  untested: { className: 'badge badge--muted', label: 'Not tested' },
} as const

/** One line per rule with core's verdict. The web only displays it. */
export function Verdicts({ results }: { results: RuleResult[] }) {
  if (!results.length) return <p className="muted">No rules were checked.</p>
  return (
    <ul className="verdicts">
      {results.map((r) => {
        const kind = verdictKind(r)
        return (
          <li key={r.rule_id} className="verdicts__row">
            <span className={BADGE[kind].className}>{BADGE[kind].label}</span>
            <span className="verdicts__text">
              {r.source}
              {kind === 'untested' && (
                <span className="verdicts__hint">
                  Nothing this rule is about happened in this run, so it was not checked.
                </span>
              )}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
