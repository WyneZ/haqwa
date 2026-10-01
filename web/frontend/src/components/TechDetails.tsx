import { useState } from 'react'
import type { Rule } from '../api/types'
import { exceptionText } from '../lib/words'

/** Hidden by default: the exact C1 rule, for developers and judges. */
export function TechDetails({ rule }: { rule: Rule }) {
  const [open, setOpen] = useState(false)
  const fields = (['event', 'after', 'requires', 'start', 'within'] as const)
    .filter((k) => rule[k] !== undefined)
    .map((k) => `${k}: ${rule[k]}`)

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
            `pattern: ${rule.pattern} · per: ${rule.per}`,
            fields.join(' · '),
            `except: ${rule.except.length ? rule.except.map(exceptionText).join('; ') : 'none'}`,
            `confirmed examples: ${rule.confirmed_examples.length}`,
          ].join('\n')}
        </pre>
      )}
    </div>
  )
}
