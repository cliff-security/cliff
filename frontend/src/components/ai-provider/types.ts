/**
 * Frontend state machine for the AI provider modal (IMPL-0011 Phase G1).
 *
 * Discriminated union — every consumer must exhaustively handle every
 * variant. Keep this aligned with the eight states in ADR-0036.
 */

import type {
  AIProvider,
  AISource,
} from '@/api/aiProvider'

/**
 * Shared display label for a provider. Used by every component that
 * surfaces the provider name to the user so the casing + custom-label
 * stay consistent.
 */
export function providerLabel(provider: AIProvider | string | null): string {
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
      return provider ?? 'an AI provider'
  }
}

export type AIProviderState =
  | { kind: 'unconfigured' }
  | {
      kind: 'detected-pending-adoption'
      provider: AIProvider
      source: string
    }
  | { kind: 'picking-method' }
  | {
      kind: 'openrouter-pending'
      sessionId: string
      authUrl: string
      startedAt: number
    }
  | { kind: 'byok-form'; provider: AIProvider }
  | { kind: 'validating' }
  | {
      kind: 'connected'
      provider: AIProvider
      source: AISource
      metadata?: { user_email?: string; base_url?: string } | null
      overrideModel?: string | null
    }
  | { kind: 'error'; reason: string; recoverable: boolean }

export type AIProviderEvent =
  | { type: 'open' }
  | { type: 'autodetect-found'; provider: AIProvider; source: string }
  | { type: 'pick-openrouter'; sessionId: string; authUrl: string }
  | { type: 'pick-byok'; provider: AIProvider }
  | { type: 'change-byok-provider'; provider: AIProvider }
  | { type: 'submit-byok' }
  | {
      type: 'connected'
      provider: AIProvider
      source: AISource
      metadata?: { user_email?: string; base_url?: string } | null
    }
  | { type: 'error'; reason: string; recoverable: boolean }
  | { type: 'reset' }
  | { type: 'disconnect' }

/**
 * Pure reducer — used by the modal and the state-machine tests.
 * No side effects; networking lives in the components that dispatch.
 */
export function reduceAI(
  state: AIProviderState,
  event: AIProviderEvent,
): AIProviderState {
  switch (event.type) {
    case 'open':
      if (state.kind === 'connected') return state
      if (state.kind === 'detected-pending-adoption') return state
      return { kind: 'picking-method' }
    case 'autodetect-found':
      if (state.kind === 'connected') return state
      return {
        kind: 'detected-pending-adoption',
        provider: event.provider,
        source: event.source,
      }
    case 'pick-openrouter':
      return {
        kind: 'openrouter-pending',
        sessionId: event.sessionId,
        authUrl: event.authUrl,
        startedAt: Date.now(),
      }
    case 'pick-byok':
      return { kind: 'byok-form', provider: event.provider }
    case 'change-byok-provider':
      return { kind: 'byok-form', provider: event.provider }
    case 'submit-byok':
      return { kind: 'validating' }
    case 'connected':
      return {
        kind: 'connected',
        provider: event.provider,
        source: event.source,
        metadata: event.metadata,
      }
    case 'error':
      return {
        kind: 'error',
        reason: event.reason,
        recoverable: event.recoverable,
      }
    case 'reset':
      return { kind: 'picking-method' }
    case 'disconnect':
      return { kind: 'unconfigured' }
  }
}
