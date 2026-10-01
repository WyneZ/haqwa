const STEPS = ['Define', 'Test', 'Results'] as const

/** Top bar with the three steps. Only "Define" exists yet; the others show as upcoming. */
export function Header({ active = 0 }: { active?: number }) {
  return (
    <header className="topbar">
      <div className="brand">Haqwa</div>
      <nav className="steps" aria-label="Steps">
        {STEPS.map((label, i) => (
          <span
            key={label}
            className={i === active ? 'step step--active' : 'step'}
            aria-current={i === active ? 'step' : undefined}
          >
            {i + 1} {label}
          </span>
        ))}
      </nav>
    </header>
  )
}
