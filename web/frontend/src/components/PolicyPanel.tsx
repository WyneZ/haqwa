import type { ReactNode, Ref } from 'react'

export type RuleStatus = 'waiting' | 'asking' | 'confirmed' | 'unsupported'

export interface RuleRow {
  title: string
  status: RuleStatus
}

const STATUS_LABEL: Record<RuleStatus, string> = {
  waiting: 'Waiting',
  asking: 'Deciding now',
  confirmed: 'Confirmed',
  unsupported: 'Not supported yet',
}

interface Props {
  text: string
  onTextChange: (text: string) => void
  onSubmit: () => void
  onEdit: () => void
  busy: boolean
  rows: RuleRow[] | null // null = still writing the policy
  placeholder?: string
  canSubmit?: boolean
  submitLabel?: string
  onRedo?: (index: number) => void
  /** Shown under the text while writing, e.g. the policy document upload. */
  upload?: ReactNode
  textLocked?: boolean
  textareaRef?: Ref<HTMLTextAreaElement>
  submitHint?: string
}

/** Left column: the policy text, then one status line per rule. */
export function PolicyPanel({
  text,
  onTextChange,
  onSubmit,
  onEdit,
  busy,
  rows,
  placeholder,
  canSubmit = true,
  submitLabel = 'Understand my rules',
  onRedo,
  upload,
  textLocked = false,
  textareaRef,
  submitHint,
}: Props) {
  const editing = rows === null
  return (
    <aside className={editing ? 'policy policy--editing' : 'policy'} aria-busy={busy}>
      <h1 className="policy__title">Your policy</h1>
      <label htmlFor="policy" className="policy__hint" hidden={editing && textLocked}>
        Write each rule on its own line.
      </label>
      <textarea
        ref={textareaRef}
        id="policy"
        className="policy__text"
        value={text}
        placeholder={placeholder}
        onChange={(e) => onTextChange(e.target.value)}
        readOnly={!editing || textLocked}
        hidden={editing && textLocked}
        rows={7}
      />
      {editing && upload}
      {editing ? (
        <>
          <button
            type="button"
            className="btn btn--primary"
            onClick={onSubmit}
            disabled={busy || textLocked || !canSubmit || text.trim() === ''}
          >
            {busy ? 'Reading your rules…' : submitLabel}
          </button>
          {submitHint && <p className="policy__hint" aria-live="polite">{submitHint}</p>}
        </>
      ) : (
        <>
          <ol className="rules">
            {rows.map((row, i) => (
              <li key={i} className={`rules__item rules__item--${row.status}`}>
                <span className="rules__name">
                  {i + 1}. {row.title}
                </span>
                <span className="rules__status">{STATUS_LABEL[row.status]}</span>
                {row.status === 'confirmed' && onRedo && (
                  <button type="button" className="btn btn--link" onClick={() => onRedo(i)} disabled={busy}>
                    Answer again
                  </button>
                )}
              </li>
            ))}
          </ol>
          <button type="button" className="btn btn--link" onClick={onEdit}>
            Edit my rules
          </button>
        </>
      )}
    </aside>
  )
}
