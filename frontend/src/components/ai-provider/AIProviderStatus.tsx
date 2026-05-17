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
import { parseApiError } from '@/api/client'
import { useProviderTest } from '@/api/providers'
import { ModelPicker } from './ModelPicker'
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
      <section
        style={{
          background: 'var(--cd-card)',
          border: '1px solid var(--cd-rule)',
          padding: '14px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <span className="cd-loader cd-loader--sm cd-loader--cyan" aria-hidden />
        <span
          className="font-mono"
          style={{
            fontSize: 10.5,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--cd-fg-4)',
          }}
        >
          Loading provider…
        </span>
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
    <section
      style={{
        background: 'var(--cd-card)',
        border: '1px solid var(--cd-rule)',
        padding: '14px 16px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div
          style={{
            width: 36,
            height: 36,
            flexShrink: 0,
            borderRadius: 4,
            background: 'var(--cd-bg-2)',
            border: '1px solid var(--cd-rule)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--cd-fg-3)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
            aria-hidden
          >
            smart_toy
          </span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13.5,
              fontWeight: 600,
              color: 'var(--cd-fg-1)',
              marginBottom: 3,
            }}
          >
            Connect an AI provider
          </div>
          <p
            style={{
              fontSize: 12,
              color: 'var(--cd-fg-3)',
              lineHeight: 1.45,
              margin: 0,
            }}
          >
            Start enriching findings and writing fixes — two clicks via
            OpenRouter, or bring your own key.
          </p>
        </div>
        <button
          type="button"
          onClick={onConnect}
          className="cd-btn cd-btn--primary cd-btn--sm"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13 }}
            aria-hidden
          >
            bolt
          </span>
          Connect
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
  const [showPicker, setShowPicker] = useState(false)
  const provider = status.provider!
  const providerName = providerLabel(provider)
  const modelName = formatModel(status.model)
  const source = sourceCopy(status)

  // M9 (architect health-check): the drift banner + live-probe were
  // removed. The on_key_change hook restarts the singleton OpenCode
  // synchronously on every canonical-state write, so there is no drift
  // signal worth showing — and rendering one made the read look like
  // there were two sources of truth when ADR-0037 specifies one.

  // Mono detail line — source · connected timestamp. The model now has
  // its own row so it gets the breathing room it needs for the picker
  // button to live next to it without crowding.
  const detailParts: string[] = []
  detailParts.push(source)
  if (status.connected_at) {
    detailParts.push(`connected ${formatConnectedAt(status.connected_at)}`)
  }

  return (
    <section
      style={{
        background: 'var(--cd-card)',
        border: '1px solid var(--cd-rule)',
        padding: '14px 16px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div
          style={{
            width: 36,
            height: 36,
            flexShrink: 0,
            borderRadius: 4,
            background: 'var(--cd-green-soft)',
            border: '1px solid var(--cd-green-line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--cd-green)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
            aria-hidden
          >
            {providerIcon(provider)}
          </span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13.5,
              fontWeight: 600,
              color: 'var(--cd-fg-1)',
              marginBottom: 3,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {providerName}
          </div>
          <div
            className="font-mono"
            style={{
              fontSize: 10.5,
              color: 'var(--cd-fg-4)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {detailParts.join(' · ')}
          </div>
        </div>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--cd-green)',
            flexShrink: 0,
            whiteSpace: 'nowrap',
          }}
        >
          <span
            aria-hidden
            style={{
              width: 7,
              height: 7,
              borderRadius: 999,
              background: 'var(--cd-green)',
              boxShadow: '0 0 6px var(--cd-green)',
            }}
          />
          Live
        </span>
        <TestConnectionButton />
        <button
          type="button"
          onClick={onSwitch}
          className="cd-btn cd-btn--ghost cd-btn--sm"
        >
          Switch
        </button>
        <button
          type="button"
          data-testid="ai-disconnect-open"
          onClick={() => setShowDisconnect(true)}
          className="cd-btn cd-btn--danger cd-btn--sm"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13 }}
            aria-hidden
          >
            link_off
          </span>
          Disconnect
        </button>
      </div>

      {/* Model row — canonical active model + picker + drift indicator. */}
      <div
        style={{
          marginTop: 12,
          paddingLeft: 50,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
        }}
        data-testid="ai-provider-model-row"
      >
        <span
          className="font-mono"
          style={{
            fontSize: 10.5,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--cd-fg-4)',
          }}
        >
          Model
        </span>
        <span
          className="font-mono"
          style={{
            fontSize: 12,
            color: 'var(--cd-fg-1)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: '40ch',
          }}
          data-testid="ai-provider-active-model"
          title={status.model ?? undefined}
        >
          {modelName ?? 'not set'}
        </span>
        <button
          type="button"
          id="ai-provider-change-model"
          data-testid="ai-provider-change-model"
          onClick={() => setShowPicker(true)}
          className="cd-btn cd-btn--ghost cd-btn--sm"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13 }}
            aria-hidden
          >
            tune
          </span>
          Change
        </button>
      </div>

      {showPicker && (
        <ModelPicker
          provider={provider as Parameters<typeof ModelPicker>[0]['provider']}
          currentModel={status.model}
          triggerId="ai-provider-change-model"
          onClose={() => setShowPicker(false)}
        />
      )}

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
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      {verdict.kind === 'ok' && (
        <span role="status" className="cd-chip cd-chip--green">
          ✓ {verdict.latencyMs} ms
        </span>
      )}
      {verdict.kind === 'fail' && (
        <span role="alert" className="cd-chip cd-chip--red" title={verdict.message}>
          ✕ Failed
        </span>
      )}
      <button
        type="button"
        onClick={handleTest}
        disabled={test.isPending}
        className="cd-btn cd-btn--ghost cd-btn--sm"
      >
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 13 }}
          aria-hidden="true"
        >
          network_ping
        </span>
        {test.isPending ? 'Testing…' : 'Test'}
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
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(11,16,27,0.72)', backdropFilter: 'blur(4px)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div
        className="cd-frame w-full"
        style={{
          maxWidth: 440,
          background: 'var(--cd-card)',
          border: '1px solid var(--cd-rule)',
          padding: '24px 26px',
        }}
      >
        <div className="cd-frame-br" />
        <h4
          id="ai-disconnect-heading"
          className="font-display font-extrabold"
          style={{
            fontSize: 18,
            color: 'var(--cd-fg-1)',
            letterSpacing: '-0.02em',
            marginBottom: 8,
          }}
        >
          Disconnect {providerLabel(provider)}?
        </h4>
        <p style={{ fontSize: 13, color: 'var(--cd-fg-3)', lineHeight: 1.55 }}>
          cliff will remove its local copy of the key. Agents will stop
          running until you reconnect.
        </p>
        {provider === 'openrouter' && (
          <p
            style={{
              marginTop: 8,
              fontSize: 12,
              color: 'var(--cd-fg-4)',
              lineHeight: 1.55,
            }}
          >
            To fully revoke this key on OpenRouter's side, visit{' '}
            <a
              href="https://openrouter.ai/settings/keys"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--cd-cyan)' }}
            >
              openrouter.ai/settings/keys
            </a>
            .
          </p>
        )}

        {/* Safe default on the right: destructive action sits on the left,
            keep-connected primary on the right. Cancel is the focused
            default on mount so Enter/Esc both bias toward "don't lose
            the connection". */}
        <div
          style={{
            marginTop: 20,
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
          }}
        >
          <button
            type="button"
            data-testid="ai-disconnect-confirm"
            onClick={async () => {
              await disconnect.mutateAsync()
              onConfirmed()
            }}
            disabled={disconnect.isPending}
            className="cd-btn cd-btn--danger cd-btn--sm"
          >
            {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
          </button>
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="cd-btn cd-btn--primary cd-btn--sm"
          >
            Keep connected
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
