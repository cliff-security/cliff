/**
 * IssueFilterSelect — Cliff Cyberdeck dropdown filter.
 *
 * Mirrors `FilterSelect` from `ui-kit/issues.jsx` exactly:
 *  - mono uppercase label inside the trigger ("TYPE: ALL")
 *  - sage tinted trigger + sage label when a non-default value is selected
 *  - dropdown panel under the trigger, options in mono with optional
 *    severity dot, count on the right
 *  - click-outside closes
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'

/**
 * Hover state for the dropdown rows. The ui-kit prototype renders a
 * sage-soft fill on hover that's visually distinct from the selected
 * sage-soft (which also gets sage text). Plain rows go from
 * `transparent` → `rgba(214,224,244,0.04)` so the row "lights up"
 * without competing with the selected indicator.
 */

export interface FilterOption {
  /** Stable id for selection (`'all'` is the default, treated as inactive). */
  id: string
  /** Label shown in the trigger + the dropdown row. */
  label: string
  /** Optional count rendered on the right of each row. */
  count?: number
  /** Optional severity-coded dot (CSS color value). */
  dot?: string
}

interface IssueFilterSelectProps {
  label: string
  value: string
  options: FilterOption[]
  onChange: (id: string) => void
}

export function IssueFilterSelect({
  label,
  value,
  options,
  onChange,
}: IssueFilterSelectProps) {
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState<string | null>(null)
  const [triggerHover, setTriggerHover] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const current = options.find((o) => o.id === value) ?? options[0]

  // Active means "the filter is doing something" — i.e. anything but the
  // default `all` option. Drives the sage-tinted trigger appearance.
  const isActive = value !== 'all'

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  // Trigger styling — mirrors the ui-kit FilterSelect with an added
  // hover state. Hover brightens the border (`--cd-rule` → `--cd-rule-2`)
  // and faintly lifts the background, signaling clickability without
  // committing to the sage-active visual.
  const lit = triggerHover || open
  const triggerStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '7px 12px',
    fontFamily: 'var(--cd-sans)',
    fontSize: 13,
    fontWeight: 500,
    letterSpacing: 0,
    textTransform: 'none',
    background: isActive
      ? lit
        ? 'rgba(111, 227, 181, 0.14)'
        : 'rgba(111, 227, 181, 0.08)'
      : lit
        ? 'rgba(214, 224, 244, 0.05)'
        : 'transparent',
    color: isActive ? 'var(--cd-green)' : lit ? 'var(--cd-fg-1)' : 'var(--cd-fg-2)',
    border: `1px solid ${
      isActive
        ? 'var(--cd-green-line)'
        : lit
          ? 'var(--cd-rule-2)'
          : 'var(--cd-rule)'
    }`,
    borderRadius: 2,
    cursor: 'pointer',
    minWidth: 180,
    justifyContent: 'space-between',
    transition: 'background var(--cd-fast), border-color var(--cd-fast), color var(--cd-fast)',
    lineHeight: 1.2,
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setTriggerHover(true)}
        onMouseLeave={() => setTriggerHover(false)}
        style={triggerStyle}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {current.dot && (
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 999,
                background: current.dot,
                boxShadow: `0 0 5px ${current.dot}`,
              }}
              aria-hidden
            />
          )}
          <span style={{ color: 'var(--cd-fg-4)' }}>{label}</span>
          <span
            style={{
              color: isActive ? 'var(--cd-green)' : 'var(--cd-fg-1)',
              fontWeight: 600,
            }}
          >
            {current.label}
          </span>
        </span>
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 14, color: 'var(--cd-fg-4)' }}
          aria-hidden
        >
          {open ? 'expand_less' : 'expand_more'}
        </span>
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            minWidth: '100%',
            background: 'var(--cd-card)',
            border: '1px solid var(--cd-rule)',
            boxShadow: '0 12px 24px rgba(0,0,0,0.40)',
            zIndex: 30,
            padding: '4px 0',
            borderRadius: 2,
          }}
        >
          {options.map((o) => {
            const selected = o.id === value
            const isHovered = hovered === o.id
            // Selected wins over hover for colour; hover layers on a
            // subtle ink-soft fill so the focus is unambiguous.
            const rowBg = selected
              ? isHovered
                ? 'rgba(111, 227, 181, 0.14)'
                : 'rgba(111, 227, 181, 0.08)'
              : isHovered
                ? 'rgba(214, 224, 244, 0.05)'
                : 'transparent'
            const rowColor = selected
              ? 'var(--cd-green)'
              : isHovered
                ? 'var(--cd-fg-1)'
                : 'var(--cd-fg-2)'
            return (
              <button
                key={o.id}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(o.id)
                  setOpen(false)
                }}
                onMouseEnter={() => setHovered(o.id)}
                onMouseLeave={() => setHovered((h) => (h === o.id ? null : h))}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 14px',
                  background: rowBg,
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'var(--cd-sans)',
                  fontSize: 13,
                  fontWeight: selected ? 600 : 500,
                  letterSpacing: 0,
                  textTransform: 'none',
                  color: rowColor,
                  transition: 'background var(--cd-fast), color var(--cd-fast)',
                }}
              >
                {o.dot ? (
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 999,
                      background: o.dot,
                      boxShadow: `0 0 5px ${o.dot}`,
                    }}
                    aria-hidden
                  />
                ) : (
                  <span style={{ width: 7, height: 7 }} aria-hidden />
                )}
                <span style={{ flex: 1 }}>{o.label}</span>
                {o.count != null && (
                  <span
                    style={{
                      color: 'var(--cd-fg-4)',
                      fontWeight: 500,
                    }}
                  >
                    {o.count}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
