/**
 * AI provider connect flow — reusable in two surfaces:
 *
 * - The dismissible **modal** opened from any agent CTA or the Settings
 *   "Connect AI provider" button.
 * - The **onboarding wizard step** that lands new users on a single
 *   unified setup flow (no more legacy paste cards).
 *
 * The component routes between auto-detect adoption, OpenRouter OAuth,
 * and direct BYOK. Stateless w.r.t. its container — the parent decides
 * whether dismissal returns to the app, advances to the next wizard
 * step, etc.
 */

import { useCallback, useState } from 'react'
import { useAdopt, useAutodetect } from '@/api/aiProvider'
import { providerLabel } from './types'
import { DirectBYOKForm } from './DirectBYOKForm'
import { OpenRouterConnectFlow } from './OpenRouterConnectFlow'

type View = 'picking-method' | 'detected' | 'openrouter' | 'byok'

interface Props {
  /** Whether to fire the auto-detect query. Modal sets this on open. */
  enableAutodetect?: boolean
  /** Fired once a provider has been connected end-to-end. */
  onConnected: () => void
  /** Rendered as the "dismiss / maybe later" CTA on the picking screen.
   *  Onboarding hides it; the modal uses it to close. */
  onDismiss?: () => void
  /** Optional dismiss label override — onboarding hides this entirely. */
  dismissLabel?: string
}

export function AIProviderFlow({
  enableAutodetect = true,
  onConnected,
  onDismiss,
  dismissLabel = 'Maybe later',
}: Props) {
  const autodetect = useAutodetect(enableAutodetect)
  const adopt = useAdopt()
  const [userOverride, setUserOverride] = useState<View | null>(null)

  const view: View =
    userOverride ??
    (autodetect.data?.found ? 'detected' : 'picking-method')

  const handleConnected = useCallback(() => {
    onConnected()
  }, [onConnected])

  if (view === 'detected' && autodetect.data?.found) {
    return (
      <DetectedPanel
        provider={autodetect.data.provider!}
        source={autodetect.data.source!}
        onAdopt={async () => {
          await adopt.mutateAsync()
          handleConnected()
        }}
        onDecline={() => setUserOverride('picking-method')}
        adopting={adopt.isPending}
        error={adopt.error instanceof Error ? adopt.error.message : null}
      />
    )
  }

  if (view === 'picking-method') {
    return (
      <PickingMethodPanel
        onPickOpenRouter={() => setUserOverride('openrouter')}
        onPickBYOK={() => setUserOverride('byok')}
        onDismiss={onDismiss}
        dismissLabel={dismissLabel}
      />
    )
  }

  if (view === 'openrouter') {
    return (
      <OpenRouterConnectFlow
        onConnected={handleConnected}
        onSwitchToBYOK={() => setUserOverride('byok')}
        onClose={onDismiss ?? (() => setUserOverride('picking-method'))}
      />
    )
  }

  // view === 'byok'
  return (
    <DirectBYOKForm
      initialProvider="anthropic"
      onConnected={handleConnected}
      onCancel={() => setUserOverride('picking-method')}
    />
  )
}

function PickingMethodPanel({
  onPickOpenRouter,
  onPickBYOK,
  onDismiss,
  dismissLabel,
}: {
  onPickOpenRouter: () => void
  onPickBYOK: () => void
  onDismiss?: () => void
  dismissLabel: string
}) {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="font-headline text-2xl font-semibold text-on-surface">
          Pick a path
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
          OpenSec uses an AI provider to enrich findings and write fixes.
          The recommended path is two clicks.
        </p>
      </header>

      <button
        type="button"
        data-testid="open-openrouter"
        onClick={onPickOpenRouter}
        className="group flex w-full items-center justify-between rounded-2xl bg-primary px-6 py-5 text-left text-on-primary shadow-sm transition hover:shadow-md"
      >
        <div>
          <p className="font-headline text-base font-semibold">
            Connect with OpenRouter
          </p>
          <p className="mt-1 text-sm opacity-90">
            One account, every model. Recommended.
          </p>
        </div>
        <span className="material-symbols-outlined">arrow_forward</span>
      </button>

      <button
        type="button"
        data-testid="open-byok"
        onClick={onPickBYOK}
        className="block text-sm font-medium text-primary hover:underline"
      >
        I have my own API key →
      </button>

      {onDismiss && (
        <div className="flex justify-end pt-2">
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
          >
            {dismissLabel}
          </button>
        </div>
      )}
    </div>
  )
}

function DetectedPanel({
  provider,
  source,
  onAdopt,
  onDecline,
  adopting,
  error,
}: {
  provider: string
  source: string
  onAdopt: () => void
  onDecline: () => void
  adopting: boolean
  error: string | null
}) {
  const friendlyProvider = providerLabel(provider)
  return (
    <div className="space-y-6">
      <header>
        <h2 className="font-headline text-2xl font-semibold text-on-surface">
          We found a {friendlyProvider} key in your environment
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
          OpenSec can use it — encrypted at rest, never logged.
        </p>
        <p className="mt-2 rounded-xl bg-surface-container px-3 py-2 font-mono text-xs text-on-surface-variant">
          {source}
        </p>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-xl bg-error-container px-4 py-3 text-sm leading-relaxed text-on-error-container"
        >
          {error}
        </p>
      )}

      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={onDecline}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          No, set up something else
        </button>
        <button
          type="button"
          data-testid="adopt-detected"
          onClick={onAdopt}
          disabled={adopting}
          className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
        >
          {adopting ? 'Connecting…' : 'Use it'}
        </button>
      </div>
    </div>
  )
}
