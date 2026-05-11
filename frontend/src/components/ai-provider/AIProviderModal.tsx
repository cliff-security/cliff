/**
 * Root modal for AI provider onboarding (IMPL-0011 G3).
 *
 * State-machine router that mounts the right sub-component for the
 * current state. Dismissible — closing leaves the app browsable with
 * agent buttons disabled (tooltip via useAIRequired).
 *
 * Serene Sentinel rules:
 *   - tonal layering, no 1px borders
 *   - sentence case throughout
 *   - Manrope headings (font-headline), Inter body
 *   - primary CTAs use bg-primary text-on-primary
 *   - Material Symbols icons via the `material-symbols-outlined` class
 */

import { useCallback, useEffect, useState } from 'react'
import { useAdopt, useAutodetect } from '@/api/aiProvider'
import { DirectBYOKForm } from './DirectBYOKForm'
import { OpenRouterConnectFlow } from './OpenRouterConnectFlow'

interface Props {
  open: boolean
  onClose: () => void
  /** Optional callback fired once the user reaches a connected state. */
  onConnected?: () => void
}

type View =
  | 'picking-method'
  | 'detected'
  | 'openrouter'
  | 'byok'
  | 'connected-success'

export function AIProviderModal(props: Props) {
  if (!props.open) return null
  // Remount the inner panel each time the modal opens so picker state
  // can't leak across sessions. Avoids a setState-in-effect reset.
  return <AIProviderModalInner {...props} />
}

function AIProviderModalInner({ open, onClose, onConnected }: Props) {
  // Tracks any explicit navigation the user has done inside the modal.
  // When null, the view is *derived* from autodetect's outcome — that
  // keeps us out of setState-in-effect territory while preserving the
  // "show the detected card unless the user moved on" behavior.
  const [userOverride, setUserOverride] = useState<View | null>(null)
  const autodetect = useAutodetect(open)
  const adopt = useAdopt()

  const view: View =
    userOverride ??
    (autodetect.data?.found ? 'detected' : 'picking-method')

  // Close on Esc.
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const handleConnected = useCallback(() => {
    onConnected?.()
    onClose()
  }, [onConnected, onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI provider setup"
      data-testid="ai-provider-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4 py-10"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-xl rounded-3xl bg-surface p-8 shadow-xl">
        {view === 'detected' && autodetect.data?.found && (
          <DetectedPanel
            provider={autodetect.data.provider!}
            source={autodetect.data.source!}
            onAdopt={async () => {
              await adopt.mutateAsync()
              handleConnected()
            }}
            onDecline={() => setUserOverride('picking-method')}
            adopting={adopt.isPending}
            error={
              adopt.error instanceof Error ? adopt.error.message : null
            }
          />
        )}

        {view === 'picking-method' && (
          <PickingMethodPanel
            onPickOpenRouter={() => setUserOverride('openrouter')}
            onPickBYOK={() => setUserOverride('byok')}
            onClose={onClose}
          />
        )}

        {view === 'openrouter' && (
          <OpenRouterConnectFlow
            onConnected={handleConnected}
            onSwitchToBYOK={() => setUserOverride('byok')}
            onClose={onClose}
          />
        )}

        {view === 'byok' && (
          <DirectBYOKForm
            initialProvider="anthropic"
            onConnected={handleConnected}
            onCancel={() => setUserOverride('picking-method')}
          />
        )}
      </div>
    </div>
  )
}

function PickingMethodPanel({
  onPickOpenRouter,
  onPickBYOK,
  onClose,
}: {
  onPickOpenRouter: () => void
  onPickBYOK: () => void
  onClose: () => void
}) {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="font-headline text-2xl font-semibold text-on-surface">
          Connect an AI provider
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

      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          Maybe later
        </button>
      </div>
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
  const friendlyProvider = friendlyName(provider)
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

function friendlyName(provider: string): string {
  switch (provider) {
    case 'anthropic':
      return 'Anthropic'
    case 'openrouter':
      return 'OpenRouter'
    case 'openai':
      return 'OpenAI'
    default:
      return provider
  }
}
