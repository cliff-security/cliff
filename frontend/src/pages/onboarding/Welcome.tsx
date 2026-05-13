import { useLayoutEffect } from 'react'
import { useNavigate } from 'react-router'

/**
 * Onboarding frame 1.0 — "Welcome · first launch".
 * Centered hero, single "Get started" CTA, no progress bar (wizard starts
 * on the next page). Soft gradient backdrop mirrors the mockup.
 */
export default function Welcome() {
  const navigate = useNavigate()

  // No sidebar on this route — pin the registration marks to the
  // viewport corners instead of offsetting for a sidebar that isn't
  // rendered. Mirrors OnboardingShell's behaviour. `useLayoutEffect`
  // keeps the body attribute coherent across paint frames during
  // route transitions.
  useLayoutEffect(() => {
    document.body.dataset.cliffFrame = 'viewport'
    return () => {
      delete document.body.dataset.cliffFrame
    }
  }, [])

  return (
    <div
      className="min-h-screen relative overflow-hidden flex flex-col items-center justify-center px-6 py-20"
      style={{ background: 'var(--cd-bg)' }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(circle at 20% 0%, rgba(111,227,181,0.06), transparent 45%), radial-gradient(circle at 100% 100%, rgba(127,200,220,0.04), transparent 45%)',
        }}
      />

      <div className="relative text-center max-w-xl">
        <div
          className="inline-flex items-baseline mb-5"
          style={{ lineHeight: 1 }}
        >
          <span
            className="font-display font-extrabold"
            style={{
              fontSize: 64,
              letterSpacing: '-0.045em',
              color: 'var(--cd-green)',
              textShadow: '0 0 24px var(--cd-green-glow)',
            }}
          >
            cliff
          </span>
          <span
            className="cd-pulse"
            style={{
              width: 12,
              height: 12,
              background: 'var(--cd-green)',
              boxShadow: '0 0 14px var(--cd-green)',
              marginLeft: 6,
            }}
            aria-hidden
          />
        </div>
        <h1
          className="font-display font-extrabold mb-3"
          style={{
            fontSize: 30,
            letterSpacing: '-0.03em',
            color: 'var(--cd-fg-1)',
          }}
        >
          your security operator, ready.
        </h1>
        <p
          className="text-lg leading-relaxed mb-10"
          style={{ color: 'var(--cd-fg-3)' }}
        >
          In three short steps we'll connect your repository, set up your AI
          model, and run an assessment. Most maintainers are done in under
          three minutes.
        </p>
        <div className="flex items-center justify-center">
          <button
            type="button"
            onClick={() => navigate('/onboarding/connect')}
            className="cd-btn cd-btn--primary"
            style={{ padding: '10px 18px', fontSize: 11 }}
          >
            <span className="material-symbols-outlined" aria-hidden="true" style={{ fontSize: 14 }}>
              play_arrow
            </span>
            Get started
          </button>
        </div>
        <p
          className="mt-8 text-xs font-mono uppercase"
          style={{ color: 'var(--cd-fg-4)', letterSpacing: '0.18em' }}
        >
          self-hosted · credentials never leave this machine
        </p>
      </div>
    </div>
  )
}
