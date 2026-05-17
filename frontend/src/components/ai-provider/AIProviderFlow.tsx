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
import {
  describeAutodetectSource,
  providerIcon,
  providerLabel,
} from './types'
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
          How would you like to connect?
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
          Cliff needs an AI provider to enrich findings and write fixes.
          Encrypted at rest, never leaves your machine.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <button
          type="button"
          data-testid="open-openrouter"
          onClick={onPickOpenRouter}
          className="group relative flex h-full flex-col gap-3 rounded-2xl bg-primary p-5 text-left text-on-primary shadow-sm transition hover:shadow-md"
        >
          <span className="inline-flex items-center gap-2 self-start rounded-full bg-on-primary/15 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
            Recommended
          </span>
          <span
            className="material-symbols-outlined text-[28px]"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1, 'wght' 500" }}
          >
            {providerIcon('openrouter')}
          </span>
          <div className="flex-1">
            <p className="font-headline text-base font-semibold">
              Connect with OpenRouter
            </p>
            <p className="mt-1 text-sm leading-relaxed opacity-90">
              Sign in once. Every model, one bill. Two clicks.
            </p>
          </div>
          <span className="inline-flex items-center gap-1 text-sm font-medium opacity-95">
            Continue
            <span className="material-symbols-outlined text-[18px]">
              arrow_forward
            </span>
          </span>
        </button>

        <button
          type="button"
          data-testid="open-byok"
          onClick={onPickBYOK}
          className="group flex h-full flex-col gap-3 rounded-2xl bg-surface-container-high p-5 text-left text-on-surface transition hover:bg-surface-container-highest"
        >
          <span
            className="material-symbols-outlined text-[28px] text-primary"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 0, 'wght' 500" }}
          >
            vpn_key
          </span>
          <div className="flex-1">
            <p className="font-headline text-base font-semibold">
              I have my own API key
            </p>
            <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
              Bring an existing Anthropic, OpenAI, or compatible key.
            </p>
          </div>
          <span className="inline-flex items-center gap-1 text-sm font-medium text-primary">
            Paste it
            <span className="material-symbols-outlined text-[18px]">
              arrow_forward
            </span>
          </span>
        </button>
      </div>

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
  const friendlySource = describeAutodetectSource(source)
  return (
    <div className="space-y-6">
      <header className="flex items-start gap-4">
        <span
          className="material-symbols-outlined flex-shrink-0 rounded-2xl bg-primary-container/40 p-3 text-[28px] text-primary"
          aria-hidden="true"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {providerIcon(provider)}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="font-headline text-2xl font-semibold text-on-surface">
            Use your {friendlyProvider} key?
          </h2>
          <p
            className="mt-2 text-sm leading-relaxed text-on-surface-variant"
            title={source}
          >
            We spotted one in <span className="font-medium text-on-surface">{friendlySource}</span>.
            Cliff can adopt it — encrypted at rest, never logged.
          </p>
        </div>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-xl bg-error-container px-4 py-3 text-sm leading-relaxed text-on-error-container"
        >
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={onDecline}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          Pick a different path
        </button>
        <button
          type="button"
          data-testid="adopt-detected"
          onClick={onAdopt}
          disabled={adopting}
          className="rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
        >
          {adopting ? 'Connecting…' : 'Use this key'}
        </button>
      </div>
    </div>
  )
}
