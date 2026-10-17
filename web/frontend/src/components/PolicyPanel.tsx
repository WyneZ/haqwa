import type { ReactNode } from 'react'

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
  onRedo?: (index: number) => void
  /** Shown under the text while writing, e.g. the policy document upload. */
  upload?: ReactNode
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
  onRedo,
  upload,
}: Props) {
  const editing = rows === null
  return (
    <aside className={editing ? 'policy policy--editing' : 'policy'} aria-busy={busy}>
      <h1 className="policy__title">Your policy</h1>
      <label htmlFor="policy" className="policy__hint">
        Write each rule on its own line.
      </label>
      <textarea
        id="policy"
        className="policy__text"
        value={text}
        placeholder={placeholder}
        onChange={(e) => onTextChange(e.target.value)}
        readOnly={!editing}
        rows={7}
      />
      {editing && upload}
      {editing ? (
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSubmit}
          disabled={busy || !canSubmit || text.trim() === ''}
        >
          {busy ? 'Reading your rules…' : 'Understand my rules'}
        </button>
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
