import { useState } from 'react'
import type { ConfirmedExample, RuleV2 } from '../api/types'
import { nodeText } from '../lib/words'

/** Hidden by default: exact v2 parameters and the unedited code-generated meaning. */
export function TechDetails({ rule, meaning, confirmedExamples = [] }: {
  rule: RuleV2; meaning: string; confirmedExamples?: ConfirmedExample[]
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="tech">
      <button
        type="button"
        className="btn btn--link"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? 'Hide technical details' : 'Show technical details'}
      </button>
      {open && (
        <pre className="tech__box">
          {[
            `id: ${rule.id}`,
            `parsed meaning (before decisions): ${meaning}`,
            `root: ${rule.root} · per: ${rule.per}`,
            ...rule.nodes.map(nodeText),
            `confirmed examples: ${confirmedExamples.length}`,
          ].join('\n')}
        </pre>
      )}
    </div>
  )
}
