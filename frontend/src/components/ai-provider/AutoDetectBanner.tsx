/**
 * Non-intrusive banner shown on /dashboard and /issues when auto-detect
 * finds an existing AI key and no integration is configured (IMPL-0011 G6).
 *
 * Tonal — never red, never yellow. sessionStorage-dismissible.
 */

import { useState } from 'react'
import {
  useAdopt,
  useAIProviderStatus,
  useAutodetect,
} from '@/api/aiProvider'

const DISMISS_KEY = 'opensec.aiAutodetectBanner.dismissed'

interface Props {
  onConfigureManually: () => void
}

export function AutoDetectBanner({ onConfigureManually }: Props) {
  const [dismissed, setDismissed] = useState(
    typeof window !== 'undefined' &&
      window.sessionStorage.getItem(DISMISS_KEY) === '1',
  )
  const status = useAIProviderStatus()
  const autodetect = useAutodetect(!dismissed && status.data?.state !== 'connected')
  const adopt = useAdopt()

  if (dismissed) return null
  if (status.data?.state === 'connected') return null
  if (!autodetect.data?.found) return null
  if (autodetect.data.provider === null || autodetect.data.source === null) {
    return null
  }

  const dismiss = () => {
    window.sessionStorage.setItem(DISMISS_KEY, '1')
    setDismissed(true)
  }

  const handleAdopt = async () => {
    try {
      await adopt.mutateAsync()
      dismiss()
    } catch {
      // Error stays visible via mutation state; user can retry or dismiss.
    }
  }

  const providerName = friendly(autodetect.data.provider)

  return (
    <div
      role="status"
      data-testid="autodetect-banner"
      className="flex flex-wrap items-center gap-4 rounded-2xl bg-surface-container px-5 py-4 text-sm text-on-surface"
    >
      <span className="material-symbols-outlined text-primary">key</span>
      <div className="flex-1 min-w-0">
        <p className="font-medium">
          We found a {providerName} API key in your environment.
        </p>
        <p className="text-xs text-on-surface-variant">
          Use it for OpenSec? It's encrypted at rest and never logged.
        </p>
        {adopt.error && (
          <p className="mt-1 text-xs text-error">
            We couldn't validate that key. Try the connect flow instead.
          </p>
        )}
      </div>
      <div className="flex flex-shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => {
            dismiss()
            onConfigureManually()
          }}
          className="rounded-full px-4 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high"
        >
          No, set up something else
        </button>
        <button
          type="button"
          data-testid="autodetect-use-it"
          onClick={handleAdopt}
          disabled={adopt.isPending}
          className="rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary disabled:opacity-60"
        >
          {adopt.isPending ? 'Connecting…' : 'Use it'}
        </button>
      </div>
    </div>
  )
}

function friendly(provider: string): string {
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
