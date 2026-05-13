import { useLayoutEffect, type ReactNode } from 'react'
import StepProgress from './StepProgress'

export interface OnboardingShellProps {
  /** Step number to highlight in the progress bar. Omit on the Welcome
   *  screen (which has no progress bar). */
  step?: 1 | 2 | 3
  children: ReactNode
}

/**
 * Onboarding wizard shell — Cliff Cyberdeck.
 *
 * Centered narrow column on the navy app background, with the wordmark
 * pulse-dot at top for brand continuity. Per the critique: "the
 * onboarding lockup should appear at least once outside Welcome too" —
 * so every wizard step carries a tiny `cliff` mark.
 *
 * No PageShell here on purpose — the wizard is a sub-route that lives
 * outside `AppLayout`, so the sidebar/sidenav chrome is absent and a
 * centered column is the right pattern. Depth comes from tonal layering
 * (vignettes + scanlines from `index.css`), not borders.
 */
export default function OnboardingShell({ step, children }: OnboardingShellProps) {
  // Onboarding lives outside AppLayout (no sidebar), so the global
  // L-bracket registration marks need to anchor at the true viewport
  // corners instead of offsetting for the sidebar that isn't there.
  // `useLayoutEffect` keeps the body attribute coherent across paint
  // frames during route transitions — `useEffect` could let the
  // brackets jump position for one frame.
  useLayoutEffect(() => {
    document.body.dataset.cliffFrame = 'viewport'
    return () => {
      delete document.body.dataset.cliffFrame
    }
  }, [])

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--cd-bg)',
        position: 'relative',
      }}
    >
      <div
        aria-hidden
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          background:
            'radial-gradient(circle at 18% 0%, rgba(111,227,181,0.06), transparent 45%), radial-gradient(circle at 100% 100%, rgba(127,200,220,0.04), transparent 45%)',
        }}
      />
      <div
        className="mx-auto"
        style={{
          maxWidth: 576,
          padding: '64px 24px 80px',
          position: 'relative',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 4,
            justifyContent: 'center',
            marginBottom: 36,
          }}
        >
          <span
            className="font-display font-extrabold"
            style={{
              fontSize: 22,
              letterSpacing: '-0.045em',
              color: 'var(--cd-green)',
              textShadow: '0 0 12px var(--cd-green-glow)',
              lineHeight: 1,
            }}
          >
            cliff
          </span>
          <span
            className="cd-pulse"
            aria-hidden
            style={{
              width: 5,
              height: 5,
              marginLeft: 3,
              background: 'var(--cd-green)',
              boxShadow: '0 0 8px var(--cd-green)',
            }}
          />
        </div>
        {step !== undefined && <StepProgress current={step} />}
        {children}
      </div>
    </div>
  )
}
