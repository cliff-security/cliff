/**
 * Model picker popover (ADR-0037).
 *
 * Lists suggested models from ``GET /api/integrations/ai/models?provider=X``
 * — a curated catalog for cloud providers, a live ``/api/tags`` proxy for
 * Ollama. Free-text input below for "use a custom model id" (paid OpenRouter
 * routes, brand-new model releases, etc.) so the picker never gates the user
 * on a stale frontend list.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useProviderModels,
  useSetModel,
  type AIProvider,
  type ProviderModelOption,
} from '@/api/aiProvider'
import { parseApiError } from '@/api/client'

interface Props {
  provider: AIProvider
  currentModel: string | null
  onClose: () => void
  /** Optional id of the trigger button, used to return focus on close. */
  triggerId?: string
}

export function ModelPicker({
  provider,
  currentModel,
  onClose,
  triggerId,
}: Props) {
  const { data, isLoading, isError, refetch } = useProviderModels(provider)
  const setModel = useSetModel()
  const [custom, setCustom] = useState('')
  const [error, setError] = useState<string | null>(null)
  const firstRef = useRef<HTMLButtonElement | null>(null)

  // Keyboard: Esc closes, Enter submits custom if focused.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  // Return focus to the trigger when the picker closes.
  useEffect(() => {
    return () => {
      if (triggerId) {
        const el = document.getElementById(triggerId)
        if (el instanceof HTMLElement) el.focus()
      }
    }
  }, [triggerId])

  // Auto-focus the first option so keyboard nav works immediately.
  useEffect(() => {
    if (firstRef.current) firstRef.current.focus()
  }, [data?.models.length])

  const options = useMemo<ProviderModelOption[]>(
    () => data?.models ?? [],
    [data],
  )
  const defaultId = data?.default_model ?? null

  async function pick(id: string) {
    setError(null)
    try {
      await setModel.mutateAsync(id)
      onClose()
    } catch (err) {
      setError(parseApiError(err).message || 'Could not save.')
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-picker-heading"
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(11,16,27,0.72)', backdropFilter: 'blur(4px)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="cd-frame w-full"
        style={{
          maxWidth: 520,
          background: 'var(--cd-card)',
          border: '1px solid var(--cd-rule)',
          padding: '22px 24px',
        }}
      >
        <div className="cd-frame-br" />
        <header style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h4
            id="model-picker-heading"
            className="font-display font-extrabold"
            style={{
              fontSize: 17,
              color: 'var(--cd-fg-1)',
              letterSpacing: '-0.02em',
              margin: 0,
            }}
          >
            Choose a model
          </h4>
          <span
            className="font-mono"
            style={{
              fontSize: 10.5,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: 'var(--cd-fg-4)',
            }}
          >
            {data?.source === 'live' ? 'live from ollama' : 'catalog'}
          </span>
        </header>

        <p
          style={{
            marginTop: 6,
            fontSize: 12.5,
            color: 'var(--cd-fg-3)',
            lineHeight: 1.5,
          }}
        >
          {provider === 'ollama'
            ? 'Pulled models on your local Ollama install.'
            : `Suggested models for ${provider}. Pick one or paste a custom id below.`}
        </p>

        {isLoading && (
          <p
            className="font-mono"
            style={{
              marginTop: 14,
              fontSize: 11,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: 'var(--cd-fg-4)',
            }}
          >
            Loading models…
          </p>
        )}

        {isError && (
          <p
            role="alert"
            style={{
              marginTop: 14,
              fontSize: 12.5,
              color: 'var(--cd-red, #d33)',
            }}
          >
            Could not load the model list.{' '}
            <button
              type="button"
              onClick={() => refetch()}
              className="cd-btn cd-btn--ghost cd-btn--sm"
              style={{ marginLeft: 6 }}
            >
              Retry
            </button>
          </p>
        )}

        {!isLoading && !isError && options.length === 0 && provider === 'ollama' && (
          <p
            style={{
              marginTop: 14,
              fontSize: 12.5,
              color: 'var(--cd-fg-3)',
              lineHeight: 1.55,
            }}
          >
            No Ollama models found. Pull one first, e.g.{' '}
            <code
              style={{
                padding: '1px 6px',
                background: 'var(--cd-bg-2)',
                fontSize: 11,
              }}
            >
              ollama pull llama3.2
            </code>
            , then paste the name below.
          </p>
        )}

        <ul
          style={{
            listStyle: 'none',
            padding: 0,
            margin: '14px 0 0 0',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            maxHeight: 320,
            overflowY: 'auto',
          }}
        >
          {options.map((opt, i) => {
            const isCurrent = opt.id === currentModel
            const isDefault = opt.id === defaultId
            return (
              <li key={opt.id}>
                <button
                  ref={i === 0 ? firstRef : undefined}
                  type="button"
                  disabled={setModel.isPending}
                  onClick={() => pick(opt.id)}
                  className={
                    isCurrent
                      ? 'cd-btn cd-btn--primary'
                      : 'cd-btn cd-btn--ghost'
                  }
                  style={{
                    width: '100%',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    padding: '10px 12px',
                    textAlign: 'left',
                  }}
                >
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span
                      className="font-mono"
                      style={{ fontSize: 12, color: 'var(--cd-fg-1)' }}
                    >
                      {opt.id}
                    </span>
                    {opt.description && (
                      <span
                        style={{
                          fontSize: 11.5,
                          color: 'var(--cd-fg-3)',
                          lineHeight: 1.4,
                        }}
                      >
                        {opt.description}
                      </span>
                    )}
                  </span>
                  <span
                    style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
                  >
                    {isCurrent && (
                      <span
                        className="cd-chip cd-chip--green"
                        style={{ fontSize: 10 }}
                      >
                        Active
                      </span>
                    )}
                    {!isCurrent && isDefault && (
                      <span
                        className="cd-chip"
                        style={{ fontSize: 10 }}
                      >
                        Default
                      </span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!custom.trim()) return
            pick(custom.trim())
          }}
          style={{ marginTop: 18 }}
        >
          <label
            htmlFor="model-picker-custom"
            style={{
              display: 'block',
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--cd-fg-2)',
              marginBottom: 6,
            }}
          >
            Or paste a custom model id
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              id="model-picker-custom"
              type="text"
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder={`${provider}/your-model-id`}
              className="font-mono"
              style={{
                flex: 1,
                background: 'var(--cd-bg-2)',
                color: 'var(--cd-fg-1)',
                border: '1px solid var(--cd-rule)',
                padding: '8px 10px',
                fontSize: 12,
                outline: 'none',
              }}
            />
            <button
              type="submit"
              disabled={!custom.trim() || setModel.isPending}
              className="cd-btn cd-btn--primary cd-btn--sm"
            >
              Use
            </button>
          </div>
          <p
            style={{
              marginTop: 6,
              fontSize: 11,
              color: 'var(--cd-fg-4)',
              lineHeight: 1.45,
            }}
          >
            Must start with <code>{provider}/</code>. We forward it to
            OpenCode as-is.
          </p>
        </form>

        {error && (
          <p
            role="alert"
            style={{
              marginTop: 12,
              fontSize: 12.5,
              color: 'var(--cd-red, #d33)',
              lineHeight: 1.5,
            }}
          >
            {error}
          </p>
        )}

        <div
          style={{
            marginTop: 18,
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            className="cd-btn cd-btn--ghost cd-btn--sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
