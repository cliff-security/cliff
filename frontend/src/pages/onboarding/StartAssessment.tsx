import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import OnboardingShell from '@/components/onboarding/OnboardingShell'
import WizardNav from '@/components/onboarding/WizardNav'
import AssessmentInProgressView from '@/components/dashboard/AssessmentInProgressView'
import { useAssessmentStatus } from '@/api/dashboard'
import { onboardingStorage } from './storage'

/**
 * Onboarding frame 1.5 — "Ready to assess".
 *
 * The assessment was already kicked off at step 1 (``/onboarding/repo``),
 * so by the time the user reaches this screen a real run is usually in
 * flight. We render the same ``AssessmentInProgressView`` that the
 * dashboard's re-assessment path uses — one component, two callers, no
 * cosmetic asymmetry between "first run" and "re-run".
 *
 * Auto-navigate to ``/dashboard`` when the backend flips to ``complete``.
 */
export default function StartAssessment() {
  const navigate = useNavigate()
  const assessmentId = onboardingStorage.get('assessmentId')

  // Defensive: ConnectRepo always stashes an id on success. If it's missing
  // the user probably reloaded mid-wizard — send them back to rebuild state.
  useEffect(() => {
    if (!assessmentId) navigate('/onboarding/connect')
  }, [assessmentId, navigate])

  const { data } = useAssessmentStatus(assessmentId)
  const status = data?.status

  // Auto-advance to the dashboard as soon as the backend reports complete.
  // A short dwell lets the "all five steps done" visual register before the
  // route change — same motivation as the 1.4 s verified-card dwell.
  useEffect(() => {
    if (status !== 'complete') return
    const timer = window.setTimeout(() => {
      onboardingStorage.clear()
      // Flag for the dashboard's one-time post-onboarding curtain — the
      // dashboard reads + clears this on first paint to play a brief
      // `cliff.` lockup fade-out as a celebratory hand-off.
      try {
        sessionStorage.setItem('cliff_post_onboarding', '1')
      } catch {
        // sessionStorage may throw in private mode; the curtain just
        // doesn't show, which is the safe fallback.
      }
      navigate('/dashboard')
    }, 900)
    return () => window.clearTimeout(timer)
  }, [status, navigate])

  return (
    <OnboardingShell step={3}>
      <AssessmentInProgressView
        assessmentId={assessmentId}
        headline="First assessment in progress"
        description="OpenSec is cloning your repo, scanning dependencies with Trivy, sweeping for secrets, running Semgrep, and walking the 15 posture checks. Nothing is written to your repo without your explicit approval — every change lands as a draft pull request you review."
        actions={
          <WizardNav
            onBack={() => navigate('/onboarding/ai')}
            onNext={() => {
              onboardingStorage.clear()
              try {
                sessionStorage.setItem('cliff_post_onboarding', '1')
              } catch {
                /* swallow — curtain just doesn't show in private mode */
              }
              navigate('/dashboard')
            }}
            nextLabel={
              status === 'complete' ? 'Go to dashboard' : 'Skip to dashboard'
            }
            nextIcon={status === 'complete' ? 'arrow_forward' : 'skip_next'}
          />
        }
      />
    </OnboardingShell>
  )
}
