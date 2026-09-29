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
}

/** Left column: the policy text, then one status line per rule. */
export function PolicyPanel({ text, onTextChange, onSubmit, onEdit, busy, rows }: Props) {
  const editing = rows === null
  return (
    <aside className="policy">
      <h1 className="policy__title">Your policy</h1>
      <label htmlFor="policy" className="policy__hint">
        Write each rule on its own line.
      </label>
      <textarea
        id="policy"
        className="policy__text"
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        readOnly={!editing}
        rows={7}
      />
      {editing ? (
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSubmit}
          disabled={busy || text.trim() === ''}
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
