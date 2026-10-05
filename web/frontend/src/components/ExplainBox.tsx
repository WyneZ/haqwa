import { useState } from 'react'
import { explainViolation, friendlyError } from '../api/client'
import type { Rule, Violation } from '../api/types'
import { usePersistentState } from '../lib/persist'

interface Props {
  rule: Rule
  violation: Violation
}

/**
 * "Why did this happen?" — an AI suggestion, asked only when the owner clicks
 * (saves the free-tier quota). Shown apart from the verdict and labelled: it never
 * changes what core decided. The answer is kept for this tab, so a refresh does not
 * ask the AI again.
 */
export function ExplainBox({ rule, violation }: Props) {
  const key = `explain:${violation.rule_id}:${violation.entity}:${violation.message}`
  const [text, setText] = usePersistentState<string | null>(key, null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function ask() {
    setBusy(true)
    setError(null)
    try {
      setText((await explainViolation(rule, violation)).text)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="explain" aria-labelledby="explain-title">
      <div className="explain__head">
        <h3 id="explain-title" className="explain__title">
          Why did this happen?
        </h3>
        <span className="tag">AI suggestion</span>
      </div>
      {text ? (
        <p className="explain__text">{text}</p>
      ) : (
        <button type="button" className="btn btn--ghost" onClick={ask} disabled={busy}>
          {busy ? 'Asking the AI…' : 'Explain it to me'}
        </button>
      )}
      {error && (
        <p className="notice notice--error" role="alert">
          {error} The result above is still correct.
        </p>
      )}
      <p className="explain__note">
        The AI only explains. Whether the rule was broken was decided by Haqwa’s checker.
      </p>
    </section>
  )
}
