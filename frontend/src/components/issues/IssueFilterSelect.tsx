/**
 * IssueFilterSelect — Cliff Cyberdeck dropdown filter.
 *
 * Mirrors `FilterSelect` from `ui-kit/issues.jsx`:
 *  - sentence-case trigger ("Type All") in proportional sans
 *  - sage tinted trigger + sage label when a non-default value is selected
 *  - dropdown panel under the trigger, options in sans 13px with optional
 *    severity dot, count on the right
 *  - click-outside closes
 *  - arrow-key keyboard nav (↑ / ↓ / Home / End / Enter / Esc) so
 *    keyboard users get parity with mouse users
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from 'react'

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

// Static-portion styles for the dropdown panel + options. Hoisted out of
// render per code review #4 — these never change so they shouldn't be
// recreated on every render.
const PANEL_STYLE: CSSProperties = {
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
}

const OPTION_BASE_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  width: '100%',
  textAlign: 'left',
  padding: '8px 14px',
  border: 'none',
  cursor: 'pointer',
  fontFamily: 'var(--cd-sans)',
  fontSize: 13,
  letterSpacing: 0,
  textTransform: 'none',
  transition: 'background var(--cd-fast), color var(--cd-fast)',
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
  /** User-driven keyboard cursor override. `null` means "use the
   *  selected value's index". Set by arrow keys; reset when the
   *  dropdown closes via the toggle handler. */
  const [navIdx, setNavIdx] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const current = options.find((o) => o.id === value) ?? options[0]

  // Active means "the filter is doing something" — anything but `all`.
  // Drives the sage-tinted trigger appearance.
  const isActive = value !== 'all'

  // Derive the keyboard cursor lazily — when the user hasn't pressed
  // an arrow key yet (`navIdx === null`), point at the current value.
  const selectedIdx = options.findIndex((o) => o.id === value)
  const focusedIdx =
    navIdx !== null ? navIdx : selectedIdx >= 0 ? selectedIdx : 0

  // Outside-click closes.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
        setNavIdx(null)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const commit = useCallback(
    (idx: number) => {
      const opt = options[idx]
      if (!opt) return
      onChange(opt.id)
      setOpen(false)
      setNavIdx(null)
      // Return focus to the trigger so subsequent Tab order is sensible.
      triggerRef.current?.focus()
    },
    [onChange, options],
  )

  const handleTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setOpen(true)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
    }
  }

  const handlePanelKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setNavIdx(null)
      triggerRef.current?.focus()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setNavIdx((focusedIdx + 1) % options.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setNavIdx(focusedIdx <= 0 ? options.length - 1 : focusedIdx - 1)
    } else if (e.key === 'Home') {
      e.preventDefault()
      setNavIdx(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setNavIdx(options.length - 1)
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      commit(focusedIdx)
    }
  }

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
        ? 'var(--cd-green-tint-3)'
        : 'var(--cd-green-tint-2)'
      : lit
        ? 'var(--cd-ink-tint-1)'
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
        ref={triggerRef}
        type="button"
        onClick={() =>
          setOpen((o) => {
            if (o) setNavIdx(null)
            return !o
          })
        }
        onKeyDown={handleTriggerKey}
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
          tabIndex={-1}
          onKeyDown={handlePanelKey}
          style={PANEL_STYLE}
          // Auto-focus the panel on mount so keyboard nav works without
          // an extra Tab press after Enter on the trigger.
          ref={(el) => {
            if (el) el.focus()
          }}
        >
          {options.map((o, idx) => {
            const selected = o.id === value
            const isHovered = hovered === o.id || focusedIdx === idx
            const rowBg = selected
              ? isHovered
                ? 'var(--cd-green-tint-3)'
                : 'var(--cd-green-tint-2)'
              : isHovered
                ? 'var(--cd-ink-tint-1)'
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
                onClick={() => commit(idx)}
                onMouseEnter={() => setHovered(o.id)}
                onMouseLeave={() =>
                  setHovered((h) => (h === o.id ? null : h))
                }
                style={{
                  ...OPTION_BASE_STYLE,
                  background: rowBg,
                  color: rowColor,
                  fontWeight: selected ? 600 : 500,
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
