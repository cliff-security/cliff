/**
 * Settings-page card showing the current AI provider connection
 * (IMPL-0011 G7). Includes disconnect with the openrouter.ai revoke
 * note + a "switch provider" hand-off back to the modal.
 */

import { useState } from 'react'
import {
  useAIProviderStatus,
  useDisconnect,
  type AIStatusResponse,
} from '@/api/aiProvider'

interface Props {
  onSwitchProvider: () => void
  onConnect: () => void
}

export function AIProviderStatus({ onSwitchProvider, onConnect }: Props) {
  const status = useAIProviderStatus()
  const disconnect = useDisconnect()
  const [showDisconnect, setShowDisconnect] = useState(false)

  if (status.isLoading || !status.data) {
    return (
      <section className="rounded-2xl bg-surface-container px-6 py-5">
        <p className="text-sm text-on-surface-variant">Loading…</p>
      </section>
    )
  }

  if (status.data.state === 'unconfigured') {
    return (
      <section className="rounded-2xl bg-surface-container px-6 py-5">
        <header className="flex items-center justify-between gap-4">
          <div>
            <h3 className="font-headline text-base font-semibold text-on-surface">
              AI provider
            </h3>
            <p className="mt-1 text-sm text-on-surface-variant">
              Not connected. Connect a provider to enable agents.
            </p>
          </div>
          <button
            type="button"
            onClick={onConnect}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
          >
            Connect AI provider
          </button>
        </header>
      </section>
    )
  }

  return (
    <section className="space-y-4 rounded-2xl bg-surface-container px-6 py-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="font-headline text-base font-semibold text-on-surface">
            AI provider
          </h3>
          <p className="mt-1 text-sm text-on-surface">
            {summarize(status.data)}
          </p>
          {status.data.override_model && (
            <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-warning-container px-3 py-1 text-xs text-on-warning-container">
              Custom model: {status.data.override_model}. Default recommended.
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onSwitchProvider}
            className="rounded-full px-4 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high"
          >
            Switch provider
          </button>
          <button
            type="button"
            data-testid="ai-disconnect-open"
            onClick={() => setShowDisconnect(true)}
            className="rounded-full px-4 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high"
          >
            Disconnect
          </button>
        </div>
      </header>

      {showDisconnect && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4"
        >
          <div className="w-full max-w-md rounded-3xl bg-surface p-6">
            <h4 className="font-headline text-lg font-semibold text-on-surface">
              Disconnect AI provider?
            </h4>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              OpenSec will remove its local copy of the key. To fully revoke
              this key from OpenRouter's side, visit{' '}
              <a
                href="https://openrouter.ai/settings/keys"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                openrouter.ai/settings/keys
              </a>
              .
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowDisconnect(false)}
                className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
              >
                Keep connected
              </button>
              <button
                type="button"
                data-testid="ai-disconnect-confirm"
                onClick={async () => {
                  await disconnect.mutateAsync()
                  setShowDisconnect(false)
                }}
                disabled={disconnect.isPending}
                className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
              >
                {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function summarize(s: AIStatusResponse): string {
  const provider = friendly(s.provider)
  const email =
    s.metadata && typeof s.metadata['user_email'] === 'string'
      ? (s.metadata['user_email'] as string)
      : null
  switch (s.source) {
    case 'openrouter-oauth':
      return email
        ? `Connected via OpenRouter as ${email}`
        : 'Connected via OpenRouter'
    case 'autodetect':
      return `Connected via ${provider} (auto-detected from environment)`
    case 'byok':
      return `Connected via ${provider}`
    default:
      return `Connected via ${provider}`
  }
}

function friendly(provider: string | null): string {
  switch (provider) {
    case 'anthropic':
      return 'Anthropic'
    case 'openrouter':
      return 'OpenRouter'
    case 'openai':
      return 'OpenAI'
    case 'custom':
      return 'a custom provider'
    default:
      return 'an AI provider'
  }
}
