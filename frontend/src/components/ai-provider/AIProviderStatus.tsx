/**
 * Settings-page hero card for the AI provider connection.
 *
 * Redesigned per the design critique:
 * - Promoted from a one-line summary to a hero treatment with provider
 *   monogram, active model, source description, and a Test connection
 *   affordance.
 * - Disconnect uses error-tonal styling + focuses "Keep connected" by
 *   default and lives on the LEFT of the dialog footer (away from the
 *   user's confirm-thumb).
 * - Unconfigured state inverted: positive framing, large CTA centered.
 */

import { useEffect, useRef, useState } from 'react'
import {
  useAIProviderStatus,
  useDisconnect,
  type AIStatusResponse,
} from '@/api/aiProvider'
import { useProviderTest } from '@/api/providers'
import {
  describeAutodetectSource,
  providerIcon,
  providerLabel,
} from './types'

interface Props {
  onSwitchProvider: () => void
  onConnect: () => void
}

export function AIProviderStatus({ onSwitchProvider, onConnect }: Props) {
  const status = useAIProviderStatus()

  if (status.isLoading || !status.data) {
    return (
      <section className="rounded-3xl bg-surface-container px-8 py-7">
        <p className="text-sm text-on-surface-variant">Loading…</p>
      </section>
    )
  }

  if (status.data.state === 'unconfigured') {
    return <UnconfiguredCard onConnect={onConnect} />
  }

  return (
    <ConnectedCard
      status={status.data}
      onSwitch={onSwitchProvider}
    />
  )
}

// ---------------------------------------------------------------------------
// Unconfigured
// ---------------------------------------------------------------------------

function UnconfiguredCard({ onConnect }: { onConnect: () => void }) {
  return (
    <section className="rounded-3xl bg-surface-container px-8 py-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <span
            className="material-symbols-outlined flex-shrink-0 rounded-2xl bg-primary-container/40 p-3 text-[26px] text-primary"
            aria-hidden="true"
          >
            smart_toy
          </span>
          <div>
            <p className="font-headline text-xl font-semibold text-on-surface">
              Connect an AI provider
            </p>
            <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
              Start enriching findings and writing fixes — two clicks via
              OpenRouter, or bring your own key.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onConnect}
          className="rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary shadow-sm transition hover:shadow-md"
        >
          Connect AI provider
        </button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Connected hero
// ---------------------------------------------------------------------------

function ConnectedCard({
  status,
  onSwitch,
}: {
  status: AIStatusResponse
  onSwitch: () => void
}) {
  const [showDisconnect, setShowDisconnect] = useState(false)
  const provider = status.provider!
  const providerName = providerLabel(provider)
  const modelName = formatModel(status.model)
  const source = sourceCopy(status)

  return (
    <section className="rounded-3xl bg-surface-container px-8 py-7">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="flex min-w-0 flex-1 items-start gap-4">
          <span
            className="material-symbols-outlined flex-shrink-0 rounded-2xl bg-primary-container/40 p-3 text-[26px] text-primary"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            {providerIcon(provider)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-headline text-xl font-semibold text-on-surface">
                {providerName}
              </h3>
              <span
                className="inline-flex items-center gap-1 rounded-full bg-tertiary-container/40 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-tertiary"
              >
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  check_circle
                </span>
                Connected
              </span>
            </div>
            <p className="mt-1 text-sm text-on-surface-variant">{source}</p>
            <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-sm">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-on-surface-variant">
                  Model
                </dt>
                <dd className="mt-0.5 font-mono text-sm text-on-surface">
                  {modelName ?? '—'}
                </dd>
              </div>
              {status.connected_at && (
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-on-surface-variant">
                    Connected
                  </dt>
                  <dd className="mt-0.5 text-sm text-on-surface">
                    {formatConnectedAt(status.connected_at)}
                  </dd>
                </div>
              )}
            </dl>
            {status.override_model && (
              <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-surface-container-high px-3 py-1 text-xs text-on-surface-variant">
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                >
                  tune
                </span>
                Custom model override — default recommended
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TestConnectionButton />
          <button
            type="button"
            onClick={onSwitch}
            className="rounded-full px-4 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high"
          >
            Switch provider
          </button>
          <button
            type="button"
            data-testid="ai-disconnect-open"
            onClick={() => setShowDisconnect(true)}
            className="rounded-full px-4 py-2 text-sm font-medium text-on-error-container hover:bg-error-container/60"
          >
            Disconnect
          </button>
        </div>
      </div>

      {showDisconnect && (
        <DisconnectDialog
          provider={provider}
          onCancel={() => setShowDisconnect(false)}
          onConfirmed={() => setShowDisconnect(false)}
        />
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Test connection
// ---------------------------------------------------------------------------

function TestConnectionButton() {
  const test = useProviderTest()
  const [verdict, setVerdict] = useState<
    | { kind: 'idle' }
    | { kind: 'ok'; latencyMs: number }
    | { kind: 'fail'; message: string }
  >({ kind: 'idle' })

  const handleTest = async () => {
    setVerdict({ kind: 'idle' })
    try {
      const result = await test.mutateAsync({})
      if (result.ok) {
        setVerdict({ kind: 'ok', latencyMs: result.latency_ms })
      } else {
        setVerdict({
          kind: 'fail',
          message: result.error_message ?? 'Provider rejected the request.',
        })
      }
    } catch (err) {
      setVerdict({
        kind: 'fail',
        message:
          err instanceof Error ? err.message : 'Could not reach the provider.',
      })
    }
  }

  // Verdict chip fades out after ~6s so the card returns to a calm state.
  useEffect(() => {
    if (verdict.kind === 'idle') return
    const t = setTimeout(() => setVerdict({ kind: 'idle' }), 6000)
    return () => clearTimeout(t)
  }, [verdict])

  return (
    <div className="flex items-center gap-2">
      {verdict.kind === 'ok' && (
        <span
          role="status"
          className="inline-flex items-center gap-1 rounded-full bg-tertiary-container/40 px-2.5 py-1 text-xs font-medium text-tertiary"
        >
          <span
            className="material-symbols-outlined text-[14px]"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            check_circle
          </span>
          Verified · {verdict.latencyMs} ms
        </span>
      )}
      {verdict.kind === 'fail' && (
        <span
          role="alert"
          className="inline-flex items-center gap-1 rounded-full bg-error-container/60 px-2.5 py-1 text-xs font-medium text-on-error-container"
          title={verdict.message}
        >
          <span
            className="material-symbols-outlined text-[14px]"
            aria-hidden="true"
          >
            error
          </span>
          Failed
        </span>
      )}
      <button
        type="button"
        onClick={handleTest}
        disabled={test.isPending}
        className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium text-primary hover:bg-primary-container/40 disabled:opacity-60"
      >
        <span
          className="material-symbols-outlined text-[16px]"
          aria-hidden="true"
        >
          network_ping
        </span>
        {test.isPending ? 'Testing…' : 'Test connection'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Disconnect dialog
// ---------------------------------------------------------------------------

function DisconnectDialog({
  provider,
  onCancel,
  onConfirmed,
}: {
  provider: string
  onCancel: () => void
  onConfirmed: () => void
}) {
  const disconnect = useDisconnect()
  const cancelRef = useRef<HTMLButtonElement | null>(null)

  // Focus the safe default on mount.
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-disconnect-heading"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div className="w-full max-w-md rounded-3xl bg-surface p-7 shadow-xl">
        <header className="flex items-start gap-4">
          <span
            className="material-symbols-outlined flex-shrink-0 rounded-2xl bg-error-container/60 p-2.5 text-[24px] text-on-error-container"
            aria-hidden="true"
          >
            link_off
          </span>
          <div className="flex-1 min-w-0">
            <h4
              id="ai-disconnect-heading"
              className="font-headline text-lg font-semibold text-on-surface"
            >
              Disconnect {providerLabel(provider)}?
            </h4>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              OpenSec will remove its local copy of the key. Agents will
              stop running until you reconnect.
            </p>
            {provider === 'openrouter' && (
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
                To fully revoke this key on OpenRouter's side, visit{' '}
                <a
                  href="https://openrouter.ai/settings/keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  openrouter.ai/settings/keys
                </a>
                .
              </p>
            )}
          </div>
        </header>

        <div className="mt-6 flex flex-row-reverse justify-between gap-3">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
          >
            Keep connected
          </button>
          <button
            type="button"
            data-testid="ai-disconnect-confirm"
            onClick={async () => {
              await disconnect.mutateAsync()
              onConfirmed()
            }}
            disabled={disconnect.isPending}
            className="rounded-full bg-error-container px-5 py-2.5 text-sm font-semibold text-on-error-container hover:bg-error-container/80 disabled:opacity-60"
          >
            {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function sourceCopy(s: AIStatusResponse): string {
  const provider = providerLabel(s.provider)
  const email =
    s.metadata && typeof s.metadata['user_email'] === 'string'
      ? (s.metadata['user_email'] as string)
      : null
  const sourcePath =
    s.metadata && typeof s.metadata['source_path'] === 'string'
      ? (s.metadata['source_path'] as string)
      : null
  switch (s.source) {
    case 'openrouter-oauth':
      return email
        ? `Connected via OAuth as ${email}`
        : 'Connected via OAuth'
    case 'autodetect':
      return `Auto-detected from ${
        sourcePath ? describeAutodetectSource(sourcePath) : 'your environment'
      }`
    case 'byok':
      return 'Connected with your own API key'
    default:
      return `Connected via ${provider}`
  }
}

/**
 * Compact model display. OpenCode model ids are <provider>/<model> or
 * <provider>/<route-provider>/<model>; the leading provider prefix is
 * already visible via the heading, so we strip it.
 */
function formatModel(modelId: string | null): string | null {
  if (!modelId) return null
  const parts = modelId.split('/')
  if (parts.length === 1) return modelId
  // openrouter/anthropic/claude-sonnet-4.6 → anthropic/claude-sonnet-4.6
  // anthropic/claude-sonnet-4-6           → claude-sonnet-4-6
  return parts.slice(1).join('/')
}

function formatConnectedAt(iso: string): string {
  try {
    const t = new Date(iso)
    const diff = Date.now() - t.getTime()
    const day = 86400_000
    if (diff < 60_000) return 'just now'
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)} min ago`
    if (diff < day) return `${Math.floor(diff / 3600_000)} hr ago`
    if (diff < 7 * day) return `${Math.floor(diff / day)} days ago`
    return t.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}
