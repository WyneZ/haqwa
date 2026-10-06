const STEPS = ['Define', 'Test', 'Results'] as const

interface Props {
  active: number // 0-based step
  onStartOver: () => void
}

/** Top bar with the three steps and "Start over". */
export function Header({ active, onStartOver }: Props) {
  return (
    <header className="topbar">
      <div className="brand">Haqwa</div>
      <nav className="steps" aria-label="Steps">
        {STEPS.map((label, i) => (
          <span
            key={label}
            className={i === active ? 'step step--active' : i < active ? 'step step--done' : 'step'}
            aria-current={i === active ? 'step' : undefined}
          >
            {i + 1} {label}
          </span>
        ))}
      </nav>
      <button type="button" className="btn btn--link topbar__reset" onClick={onStartOver}>
        Start over
      </button>
    </header>
  )
}
