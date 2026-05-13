/**
 * IssueFilterChip — Cliff Cyberdeck filter pill.
 *
 * Mono uppercase pill with optional leading icon and trailing count.
 * Active flips fill to sage on navy text + sage glow; inactive uses the
 * hairline ghost (cd-chip) look. Squared corners (2px) per the system.
 */
import type { ReactElement, ReactNode, CSSProperties } from 'react'

interface IssueFilterChipProps {
  children: ReactNode
  count?: number
  active?: boolean
  icon?: string
  onClick?: () => void
}

export function IssueFilterChip({
  children,
  count,
  active = false,
  icon,
  onClick,
}: IssueFilterChipProps): ReactElement {
  const activeStyle: CSSProperties = active
    ? {
        background: 'var(--cd-green)',
        color: 'var(--cd-bg)',
        borderColor: 'var(--cd-green)',
        boxShadow: '0 0 12px var(--cd-green-glow)',
      }
    : {}

  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="cd-chip cursor-pointer transition-all"
      style={{ padding: '4px 10px', fontSize: 10.5, ...activeStyle }}
    >
      {icon && (
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 13, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
          aria-hidden="true"
        >
          {icon}
        </span>
      )}
      <span>{children}</span>
      {count != null && (
        <span
          className="font-mono"
          style={{
            background: active ? 'rgba(11,16,27,0.22)' : 'transparent',
            color: active ? 'var(--cd-bg)' : 'var(--cd-fg-4)',
            border: active ? 'none' : '1px solid var(--cd-rule)',
            padding: '0 5px',
            marginLeft: 2,
            fontSize: 10,
            fontWeight: 700,
            minWidth: 18,
            textAlign: 'center',
            lineHeight: 1.4,
            borderRadius: 2,
          }}
        >
          {count}
        </span>
      )}
    </button>
  )
}
