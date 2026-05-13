interface ActionButtonProps {
  label: string
  icon?: string
  variant?: 'primary' | 'outline' | 'secondary'
  onClick: () => void
  disabled?: boolean
}

/**
 * Action button — Cliff Cyberdeck primary CTA family.
 *
 * - primary: filled sage with glow; lifts -1px on hover, snaps back on press
 * - outline: sage-edged ghost that fills on hover (used to be `outline`)
 * - secondary: muted hairline button (used to be a secondary tint)
 *
 * Mono uppercase label per the system rule (buttons read as commands).
 */
export default function ActionButton({
  label,
  icon,
  variant = 'primary',
  onClick,
  disabled,
}: ActionButtonProps) {
  const variants: Record<NonNullable<ActionButtonProps['variant']>, string> = {
    primary: 'cd-btn cd-btn--primary',
    outline: 'cd-btn cd-btn--outline',
    secondary: 'cd-btn cd-btn--ghost',
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={variants[variant]}
    >
      {icon && (
        <span
          className="material-symbols-outlined"
          aria-hidden
          style={{ fontSize: 14 }}
        >
          {icon}
        </span>
      )}
      {label}
    </button>
  )
}
