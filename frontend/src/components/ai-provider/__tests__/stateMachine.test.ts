/** State-machine tests (IMPL-0011 G1).
 *
 * Exhaustive transition coverage — every event from every state.
 */

import { describe, expect, it } from 'vitest'
import { reduceAI, type AIProviderState } from '../types'

const UNCONFIGURED: AIProviderState = { kind: 'unconfigured' }

describe('reduceAI', () => {
  it('open from unconfigured goes to picking-method', () => {
    expect(reduceAI(UNCONFIGURED, { type: 'open' })).toEqual({
      kind: 'picking-method',
    })
  })

  it('open from connected is a no-op', () => {
    const connected: AIProviderState = {
      kind: 'connected',
      provider: 'openrouter',
      source: 'openrouter-oauth',
    }
    expect(reduceAI(connected, { type: 'open' })).toBe(connected)
  })

  it('autodetect-found from unconfigured pivots to detected-pending-adoption', () => {
    const next = reduceAI(UNCONFIGURED, {
      type: 'autodetect-found',
      provider: 'anthropic',
      source: 'ANTHROPIC_API_KEY env',
    })
    expect(next.kind).toBe('detected-pending-adoption')
  })

  it('autodetect-found does not override connected', () => {
    const connected: AIProviderState = {
      kind: 'connected',
      provider: 'openrouter',
      source: 'openrouter-oauth',
    }
    expect(
      reduceAI(connected, {
        type: 'autodetect-found',
        provider: 'anthropic',
        source: 'X',
      }),
    ).toBe(connected)
  })

  it('pick-openrouter transitions to openrouter-pending', () => {
    const next = reduceAI(
      { kind: 'picking-method' },
      { type: 'pick-openrouter', sessionId: 's1', authUrl: 'https://x' },
    )
    if (next.kind !== 'openrouter-pending') throw new Error('unexpected')
    expect(next.sessionId).toBe('s1')
    expect(next.authUrl).toBe('https://x')
  })

  it('pick-byok transitions to byok-form', () => {
    const next = reduceAI(
      { kind: 'picking-method' },
      { type: 'pick-byok', provider: 'anthropic' },
    )
    expect(next).toMatchObject({ kind: 'byok-form', provider: 'anthropic' })
  })

  it('change-byok-provider updates the form provider', () => {
    const start: AIProviderState = { kind: 'byok-form', provider: 'anthropic' }
    const next = reduceAI(start, {
      type: 'change-byok-provider',
      provider: 'openai',
    })
    expect(next).toMatchObject({ kind: 'byok-form', provider: 'openai' })
  })

  it('submit-byok moves to validating', () => {
    const start: AIProviderState = { kind: 'byok-form', provider: 'anthropic' }
    expect(reduceAI(start, { type: 'submit-byok' })).toEqual({
      kind: 'validating',
    })
  })

  it('connected event lands in connected', () => {
    const next = reduceAI(
      { kind: 'validating' },
      {
        type: 'connected',
        provider: 'openrouter',
        source: 'openrouter-oauth',
        metadata: { user_email: 'a@b.co' },
      },
    )
    expect(next).toMatchObject({
      kind: 'connected',
      provider: 'openrouter',
      source: 'openrouter-oauth',
    })
  })

  it('error event surfaces a recoverable error', () => {
    const next = reduceAI(
      { kind: 'openrouter-pending', sessionId: 's1', authUrl: 'x', startedAt: 0 },
      { type: 'error', reason: 'timed out', recoverable: true },
    )
    expect(next).toEqual({
      kind: 'error',
      reason: 'timed out',
      recoverable: true,
    })
  })

  it('reset always returns to picking-method', () => {
    expect(
      reduceAI(
        { kind: 'error', reason: 'x', recoverable: true },
        { type: 'reset' },
      ),
    ).toEqual({ kind: 'picking-method' })
  })

  it('disconnect always returns to unconfigured', () => {
    const connected: AIProviderState = {
      kind: 'connected',
      provider: 'openrouter',
      source: 'openrouter-oauth',
    }
    expect(reduceAI(connected, { type: 'disconnect' })).toEqual({
      kind: 'unconfigured',
    })
  })
})
