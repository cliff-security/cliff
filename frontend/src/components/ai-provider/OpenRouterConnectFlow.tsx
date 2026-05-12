/**
 * Tier 2 — OpenRouter OAuth handshake UI (IMPL-0011 G4).
 *
 * Two-step flow: primary CTA opens the auth URL in a new tab, switches to
 * the "waiting for you to authorize" card while polling /openrouter/status.
 * On terminal success → success card; on port-3000-in-use → conflict card
 * with [Try again] / [Use my own key] fallback; on denied/timeout/error →
 * non-judgmental retry.
 */

import { useEffect, useState } from 'react'
import {
  useOpenRouterPolling,
  useOpenRouterStart,
  type OpenRouterStatusResponse,
} from '@/api/aiProvider'

interface Props {
  onConnected: () => void
  onSwitchToBYOK: () => void
  onClose: () => void
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'pending'; sessionId: string; authUrl: string }
  | { kind: 'connected' }
  | { kind: 'port-conflict' }
  | { kind: 'denied' }
  | { kind: 'timeout' }
  | { kind: 'error'; detail: string | null }

export function OpenRouterConnectFlow({
  onConnected,
  onSwitchToBYOK,
  onClose,
}: Props) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const start = useOpenRouterStart()

  const handleStart = async () => {
    setPhase({ kind: 'idle' })
    try {
      const result = await start.mutateAsync()
      window.open(result.auth_url, '_blank', 'noopener,noreferrer')
      setPhase({
        kind: 'pending',
        sessionId: result.session_id,
        authUrl: result.auth_url,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('409') || msg.includes('port_3000_in_use')) {
        setPhase({ kind: 'port-conflict' })
      } else {
        setPhase({ kind: 'error', detail: msg })
      }
    }
  }

  const handleTerminal = (status: OpenRouterStatusResponse) => {
    switch (status.status) {
      case 'connected':
        setPhase({ kind: 'connected' })
        break
      case 'denied':
        setPhase({ kind: 'denied' })
        break
      case 'timeout':
        setPhase({ kind: 'timeout' })
        break
      case 'error':
        setPhase({ kind: 'error', detail: status.detail })
        break
      case 'waiting':
        break
    }
  }

  const sessionId = phase.kind === 'pending' ? phase.sessionId : null
  useOpenRouterPolling(sessionId, handleTerminal)

  useEffect(() => {
    if (phase.kind === 'connected') {
      // Defer so the success card can render before parent flips state.
      const t = setTimeout(onConnected, 0)
      return () => clearTimeout(t)
    }
    return undefined
  }, [phase.kind, onConnected])

  if (phase.kind === 'idle') {
    return (
      <div className="space-y-6">
        <Header
          title="Connect with OpenRouter"
          body="One account, every model. Sign in with Google or GitHub, then authorize OpenSec — about thirty seconds."
        />
        <div className="rounded-2xl bg-surface-container p-5 text-sm leading-relaxed text-on-surface-variant">
          <p className="font-medium text-on-surface">What happens next</p>
          <ol className="mt-2 space-y-1 pl-5 list-decimal">
            <li>OpenRouter opens in a new tab.</li>
            <li>You sign in and authorize OpenSec.</li>
            <li>OpenSec receives your key — encrypted at rest, never logged.</li>
          </ol>
        </div>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="openrouter-start"
            onClick={handleStart}
            disabled={start.isPending}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
          >
            {start.isPending ? 'Opening…' : 'Connect with OpenRouter'}
          </button>
        </div>
      </div>
    )
  }

  if (phase.kind === 'pending') {
    return (
      <div className="space-y-6">
        <Header
          title="Waiting for you to authorize"
          body="Head to the OpenRouter tab and authorize OpenSec. We'll know the moment you're done."
        />
        <div className="rounded-2xl bg-surface-container px-5 py-8 text-center">
          <SpinnerIcon className="mx-auto h-10 w-10 text-primary" />
          <p className="mt-4 text-sm text-on-surface-variant">
            Waiting for you to authorize on openrouter.ai…
          </p>
          <a
            href={phase.authUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
          >
            Open authorization page again
          </a>
        </div>
        <p className="text-center text-xs text-on-surface-variant">
          Times out after five minutes. You can close this dialog and start over.
        </p>
      </div>
    )
  }

  if (phase.kind === 'connected') {
    return (
      <div className="space-y-6" data-testid="openrouter-success">
        <Header
          title="Connected to OpenRouter"
          body="Add five dollars of credits to unlock every model, or try free sponsored models now."
        />
        <div className="flex flex-wrap items-center gap-3">
          <a
            href="https://openrouter.ai/credits"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-surface-container px-5 py-2.5 text-sm font-medium text-on-surface hover:bg-surface-container-high"
          >
            Add credits at openrouter.ai →
          </a>
          <button
            type="button"
            onClick={onConnected}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
          >
            Start using OpenSec
          </button>
        </div>
      </div>
    )
  }

  if (phase.kind === 'port-conflict') {
    return (
      <div className="space-y-6">
        <Header
          title="Port 3000 is busy"
          body="OpenRouter needs port 3000 on your machine for a one-time secure handshake. Another app on your machine is using it — commonly a Node dev server. Close that app and try again, or set up your own API key instead."
        />
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onSwitchToBYOK}
            className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
          >
            Use my own API key
          </button>
          <button
            type="button"
            onClick={handleStart}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (phase.kind === 'denied' || phase.kind === 'timeout') {
    const isTimeout = phase.kind === 'timeout'
    return (
      <div className="space-y-6">
        <Header
          title={isTimeout ? 'Took a bit too long' : 'No problem'}
          body={
            isTimeout
              ? "The handshake timed out after five minutes. We'll start fresh whenever you're ready."
              : "We didn't get an authorization — maybe you wanted to take a different path. Try again or paste your own key."
          }
        />
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onSwitchToBYOK}
            className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
          >
            Use my own API key
          </button>
          <button
            type="button"
            onClick={handleStart}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  // phase.kind === 'error'
  return (
    <div className="space-y-6">
      <Header
        title="Something went wrong"
        body={
          phase.detail ||
          "We couldn't finish the handshake. You can try again or paste your own key."
        }
      />
      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={onSwitchToBYOK}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          Use my own API key
        </button>
        <button
          type="button"
          onClick={handleStart}
          className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

function Header({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h2 className="font-headline text-2xl font-semibold text-on-surface">
        {title}
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
        {body}
      </p>
    </div>
  )
}

function SpinnerIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className ? `${className} animate-spin` : 'animate-spin'}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="3"
      />
      <path
        d="M22 12a10 10 0 0 1-10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}
