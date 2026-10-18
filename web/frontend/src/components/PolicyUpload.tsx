import { useRef, useState, type ChangeEvent } from 'react'
import { friendlyError, readPolicyDocument } from '../api/client'
import type { PolicyDocumentResult } from '../api/types'
import { POLICY_ACCEPT } from '../lib/policyFile'

interface Props {
  disabled: boolean
  /** Called with the rules the owner kept; they replace the policy text. */
  onUse: (rules: string[]) => void
}

/**
 * "Upload a policy document": Haqwa reads the file and lists the rules it found, each with
 * the exact document text behind it. The owner ticks the ones to use; nothing is checked yet.
 */
export function PolicyUpload({ disabled, onUse }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PolicyDocumentResult | null>(null)
  const [keep, setKeep] = useState<boolean[]>([])

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // picking the same file again still triggers a read
    if (!file) return
    setReading(file.name)
    setError(null)
    setResult(null)
    try {
      const found = await readPolicyDocument(file)
      setResult(found)
      setKeep(found.rules.map(() => true))
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setReading(null)
    }
  }

  function use() {
    if (!result) return
    onUse(result.rules.filter((_, i) => keep[i]).map((r) => r.text))
    setResult(null)
  }

  const chosen = keep.filter(Boolean).length
  return (
    <div className="upload">
      <input
        ref={input}
        type="file"
        accept={POLICY_ACCEPT}
        className="upload__input"
        onChange={choose}
        disabled={disabled || reading !== null}
        aria-label="Upload a policy document"
      />
      <button
        type="button"
        className="btn btn--link"
        onClick={() => input.current?.click()}
        disabled={disabled || reading !== null}
      >
        {reading ? `Reading ${reading}…` : 'Or upload a policy document (.txt, .md, .docx, .pdf)'}
      </button>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <section className="upload__result" aria-label="Rules found in your document">
          {result.rules.length === 0 ? (
            <p>
              No checkable rules were found in <b>{result.filename}</b>. You can still type them
              above.
            </p>
          ) : (
            <>
              <p>
                Haqwa found <b>{result.rules.length}</b>{' '}
                {result.rules.length === 1 ? 'rule' : 'rules'} in <b>{result.filename}</b>. Keep
                the ones Haqwa should check:
              </p>
              <ul className="upload__list">
                {result.rules.map((rule, i) => (
                  <li key={i} className="upload__item">
                    <label>
                      <input
                        type="checkbox"
                        checked={keep[i] ?? false}
                        onChange={() => setKeep((prev) => prev.map((k, j) => (j === i ? !k : k)))}
                      />{' '}
                      {rule.text}
                    </label>
                    <blockquote className="upload__quote">From the document: “{rule.quote}”</blockquote>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="upload__actions">
            {result.rules.length > 0 && (
              <button type="button" className="btn btn--primary" onClick={use} disabled={chosen === 0}>
                Use {chosen} {chosen === 1 ? 'rule' : 'rules'}
              </button>
            )}
            <button type="button" className="btn btn--link" onClick={() => setResult(null)}>
              Cancel
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
