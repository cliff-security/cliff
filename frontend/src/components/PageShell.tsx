import type { ReactNode } from 'react'

interface PageShellProps {
  title: string
  /** Inline secondary line shown next to the title at baseline. */
  subtitle?: string
  /** Right-aligned slot for buttons / actions. */
  actions?: ReactNode
  /** @deprecated — page-header breadcrumb labels were stripped in the
   *  readability brief (E1). The H1 carries the title. The prop is
   *  retained so existing callers compile but the value is ignored. */
  breadcrumb?: string | null
  /** Optional content rendered between the topbar and the body — used
   *  for sticky filter rows (Issues) directly under the title strip. */
  toolbar?: ReactNode
  children: ReactNode
}

/**
 * PageShell — Cliff Cyberdeck themed topbar + page body.
 *
 * Sticky topbar mirroring `ui-kit/chrome.jsx` Topbar, minus the
 * decorative breadcrumb label per the readability brief (E1):
 *  - sticky bar at the top of the scroll region
 *  - background `--cd-bg-1`, hairline bottom border
 *  - 14px × 28px padding
 *  - Manrope 30px H1 + inline subtitle at baseline
 *  - actions slot on the right
 *
 * Used by every page so the title strip stays consistent across
 * Dashboard / Issues / Settings / History / etc. Filter rows go in
 * ``toolbar`` so they stack under the topbar with the same sticky
 * behavior.
 */
export default function PageShell({
  title,
  subtitle,
  actions,
  toolbar,
  children,
}: PageShellProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 20,
          padding: '16px 28px',
          borderBottom: '1px solid var(--cd-rule)',
          background: 'var(--cd-bg-1)',
          display: 'flex',
          alignItems: 'center',
          gap: 18,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 14,
              flexWrap: 'wrap',
              minWidth: 0,
            }}
          >
            <h1
              className="font-display font-extrabold"
              style={{
                fontSize: 28,
                letterSpacing: '-0.025em',
                lineHeight: 1.05,
                color: 'var(--cd-fg-1)',
                margin: 0,
              }}
            >
              {title}
            </h1>
            {subtitle && (
              <span
                style={{
                  fontSize: 14,
                  color: 'var(--cd-fg-3)',
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {subtitle}
              </span>
            )}
          </div>
        </div>
        {actions && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              flexShrink: 0,
            }}
          >
            {actions}
          </div>
        )}
      </header>

      {toolbar && (
        <div
          style={{
            position: 'sticky',
            top: 64,
            zIndex: 19,
            background: 'var(--cd-bg-2)',
            borderBottom: '1px solid var(--cd-rule)',
          }}
        >
          {toolbar}
        </div>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  )
}
