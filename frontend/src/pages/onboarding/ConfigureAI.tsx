/**
 * Onboarding step 2 — Configure AI provider (ADR-0036 / IMPL-0011).
 *
 * This is the single, unified entry point for AI provider setup. The
 * legacy 4-provider paste cards have been retired (ADR-0036): there is
 * now exactly one flow — auto-detect → OpenRouter OAuth → BYOK — and
 * it's the same flow whether the user is in the wizard, the Settings
 * page, or the dismissible modal opened from an agent CTA.
 *
 * The step is "passed" once ``useAIProviderStatus`` reports
 * ``state === "connected"``. Skipping ahead is allowed — the user can
 * always come back via Settings — but the "Continue" CTA only lights
 * up once a provider is wired.
 */

import { useNavigate } from 'react-router'
import OnboardingShell from '@/components/onboarding/OnboardingShell'
import WizardNav from '@/components/onboarding/WizardNav'
import { AIProviderFlow } from '@/components/ai-provider/AIProviderFlow'
import {
  providerLabel,
} from '@/components/ai-provider/types'
import {
  useAIProviderStatus,
  useDisconnect,
} from '@/api/aiProvider'

export default function ConfigureAI() {
  const navigate = useNavigate()
  const status = useAIProviderStatus()
  const disconnect = useDisconnect()

  const isConnected = status.data?.state === 'connected'

  const handleConnected = async () => {
    // Refresh so the status card below reflects the new state.
    await status.refetch()
  }

  const handleAdvance = () => {
    navigate('/onboarding/start')
  }

  return (
    <OnboardingShell step={2}>
      <h1 className="font-headline text-3xl font-extrabold text-on-surface mb-2">
        Connect an AI provider
      </h1>
      <p className="text-on-surface-variant mb-8">
        Cliff uses an AI provider to explain findings and draft fixes.
        Pick the path that fits — most users connect with OpenRouter in
        two clicks.
      </p>

      <div className="rounded-3xl bg-surface-container-lowest p-6 shadow-sm">
        {isConnected && status.data ? (
          <ConnectedSummary
            provider={status.data.provider}
            source={status.data.source}
            email={
              typeof status.data.metadata?.user_email === 'string'
                ? (status.data.metadata.user_email as string)
                : null
            }
            onSwitch={async () => {
              await disconnect.mutateAsync()
              await status.refetch()
            }}
            switching={disconnect.isPending}
          />
        ) : (
          <AIProviderFlow
            enableAutodetect
            onConnected={handleConnected}
            onDismiss={undefined}
          />
        )}
      </div>

      <div className="mt-6 rounded-2xl bg-primary-container/30 px-5 py-4 flex items-start gap-3">
        <span
          className="material-symbols-outlined text-primary mt-0.5"
          aria-hidden="true"
        >
          shield
        </span>
        <p className="text-sm leading-relaxed text-on-primary-container">
          Your key is encrypted at rest in the local credential vault. It
          never leaves your machine — agents talk directly to your
          provider.
        </p>
      </div>

      <WizardNav
        onBack={() => navigate('/onboarding/connect')}
        onNext={handleAdvance}
        nextLabel="Continue"
        nextDisabled={!isConnected}
      />
    </OnboardingShell>
  )
}

function ConnectedSummary({
  provider,
  source,
  email,
  onSwitch,
  switching,
}: {
  provider: string | null
  source: string | null
  email: string | null
  onSwitch: () => void
  switching: boolean
}) {
  const name = providerLabel(provider)
  const sourceCopy =
    source === 'autodetect'
      ? 'auto-detected from your environment'
      : source === 'openrouter-oauth'
        ? email
          ? `OAuth as ${email}`
          : 'OAuth'
        : 'your own API key'
  return (
    <div className="space-y-6" data-testid="onboarding-ai-connected">
      <div>
        <h2 className="font-headline text-2xl font-semibold text-on-surface">
          Connected to {name}
        </h2>
        <p className="mt-2 text-sm text-on-surface-variant">{sourceCopy}.</p>
      </div>
      <div className="rounded-2xl bg-tertiary-container/30 px-4 py-3 flex items-start gap-3">
        <span
          className="material-symbols-outlined text-tertiary"
          aria-hidden="true"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          check_circle
        </span>
        <p className="text-sm text-on-surface">
          Looking good. Click <strong>Continue</strong> to start your first
          assessment.
        </p>
      </div>
      <button
        type="button"
        onClick={onSwitch}
        disabled={switching}
        className="text-sm font-medium text-primary hover:underline disabled:opacity-60"
      >
        {switching ? 'Disconnecting…' : 'Use a different provider'}
      </button>
    </div>
  )
}
