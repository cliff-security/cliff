/**
 * PostOnboardingCurtain — one-time hand-off animation between the
 * onboarding wizard and the dashboard.
 *
 * On the dashboard's first mount after a completed onboarding flow,
 * the `cliff_post_onboarding` sessionStorage flag is set. This
 * component reads the flag on mount, renders a full-viewport sage
 * `cliff.` lockup with the pulse dot for ~900ms, then fades out and
 * clears itself. The user sees the brand moment one more time on
 * their way into the app proper.
 *
 * The flag is cleared on first read so the curtain plays exactly
 * once per onboarding flow. Reloads inside the dashboard show the
 * normal page directly.
 */
import { useEffect, useState } from 'react'

const FLAG_KEY = 'cliff_post_onboarding'

export default function PostOnboardingCurtain() {
  const [phase, setPhase] = useState<'idle' | 'visible' | 'fading' | 'gone'>(
    () => {
      if (typeof window === 'undefined') return 'gone'
      try {
        return sessionStorage.getItem(FLAG_KEY) === '1' ? 'visible' : 'gone'
      } catch {
        return 'gone'
      }
    },
  )

  useEffect(() => {
    if (phase !== 'visible') return
    // Clear immediately so a quick reload doesn't replay the curtain.
    try {
      sessionStorage.removeItem(FLAG_KEY)
    } catch {
      /* ignore — private mode */
    }

    // 700ms dwell, then 500ms fade.
    const fadeTimer = window.setTimeout(() => setPhase('fading'), 700)
    const goneTimer = window.setTimeout(() => setPhase('gone'), 1200)
    return () => {
      window.clearTimeout(fadeTimer)
      window.clearTimeout(goneTimer)
    }
  }, [phase])

  if (phase === 'gone' || phase === 'idle') return null

  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--cd-bg)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: phase === 'fading' ? 0 : 1,
        transition: 'opacity 500ms cubic-bezier(.16, 1, .3, 1)',
        pointerEvents: phase === 'fading' ? 'none' : 'auto',
      }}
    >
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at 20% 0%, rgba(111,227,181,0.06), transparent 45%), radial-gradient(circle at 100% 100%, rgba(127,200,220,0.04), transparent 45%)',
        }}
      />
      <div
        style={{
          position: 'relative',
          display: 'inline-flex',
          alignItems: 'baseline',
          lineHeight: 1,
        }}
      >
        <span
          className="font-display font-extrabold"
          style={{
            fontSize: 80,
            letterSpacing: '-0.045em',
            color: 'var(--cd-green)',
            textShadow: '0 0 32px var(--cd-green-glow)',
          }}
        >
          cliff
        </span>
        <span
          className="cd-pulse"
          aria-hidden
          style={{
            width: 14,
            height: 14,
            marginLeft: 8,
            background: 'var(--cd-green)',
            boxShadow: '0 0 16px var(--cd-green)',
          }}
        />
      </div>
    </div>
  )
}
