/**
 * Tier 3 — Direct BYOK form (IMPL-0011 G5).
 *
 * Provider tiles + deep-linked console + password-style input with live
 * validation. Save button stays disabled until validation passes. The
 * "tuned for Claude" subtitle appears for openai + custom.
 *
 * Redesigned per design-critique: dropped the dropdown for radio-style
 * provider tiles (the choice deserves visual weight), collapsed the
 * "How to get your key" instructions card into one paragraph + the
 * deep-link button (the steps were redundant with the deep link), and
 * elevated the cost callout to a calm inline note.
 */

import { useState } from 'react'
import { useByok, type AIProvider, type BYOKErrorBody } from '@/api/aiProvider'
import { parseApiError } from '@/api/client'
import { providerIcon } from './types'

interface Props {
  initialProvider: AIProvider
  onConnected: () => void
  onCancel: () => void
}

interface ProviderInfo {
  name: string
  consoleUrl: string
  consoleLabel: string
  keyHint: string
  blurb: string
}

const PROVIDERS: Record<AIProvider, ProviderInfo> = {
  anthropic: {
    name: 'Anthropic',
    consoleUrl: 'https://console.anthropic.com/settings/keys',
    consoleLabel: 'Open the Anthropic console',
    keyHint: 'sk-ant-',
    blurb: 'Generate a key in the Anthropic console and paste it below.',
  },
  openai: {
    name: 'OpenAI',
    consoleUrl: 'https://platform.openai.com/api-keys',
    consoleLabel: 'Open the OpenAI console',
    keyHint: 'sk-',
    blurb: 'Generate a key in the OpenAI platform console and paste it below.',
  },
  openrouter: {
    name: 'OpenRouter',
    consoleUrl: 'https://openrouter.ai/keys',
    consoleLabel: 'Open OpenRouter keys',
    keyHint: 'sk-or-',
    blurb: 'Generate a key in your OpenRouter account and paste it below.',
  },
  google: {
    name: 'Google AI Studio',
    consoleUrl: 'https://aistudio.google.com/apikey',
    consoleLabel: 'Open Google AI Studio',
    keyHint: 'AIza',
    blurb:
      'Generate a key in Google AI Studio. The free tier covers light agent use.',
  },
  ollama: {
    name: 'Local (Ollama)',
    consoleUrl: 'https://ollama.com/library',
    consoleLabel: 'Browse the Ollama model library',
    keyHint: '',
    blurb:
      'Talks to a local Ollama runtime. No API key — just the base URL.',
  },
  custom: {
    name: 'Custom endpoint',
    consoleUrl: '',
    consoleLabel: '',
    keyHint: '',
    blurb:
      'Any OpenAI-compatible endpoint works. Provide the base URL, model id, and a key.',
  },
}

const TILES: { id: AIProvider; subtitle: string }[] = [
  { id: 'anthropic', subtitle: 'Recommended' },
  { id: 'openai', subtitle: 'Tuned for Claude' },
  { id: 'openrouter', subtitle: 'Many models, one key' },
  { id: 'google', subtitle: 'Gemini, free tier' },
  { id: 'ollama', subtitle: 'Local, no key' },
  { id: 'custom', subtitle: 'OpenAI-compatible' },
]

export function DirectBYOKForm({
  initialProvider,
  onConnected,
  onCancel,
}: Props) {
  const [provider, setProvider] = useState<AIProvider>(initialProvider)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(
    initialProvider === 'ollama' ? 'http://localhost:11434' : '',
  )
  const [model, setModel] = useState('')
  const [error, setError] = useState<BYOKErrorBody | null>(null)
  const byok = useByok()

  const info = PROVIDERS[provider]
  const isOpenAIClass = provider === 'openai' || provider === 'custom'
  const isOllama = provider === 'ollama'
  const isCustom = provider === 'custom'

  const requiredFieldsFilled = isOllama
    ? baseUrl.length > 0
    : apiKey.length >= 4 &&
      (!isCustom || (baseUrl.length > 0 && model.length > 0))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await byok.mutateAsync({
        provider,
        // Ollama: server requires non-empty api_key field; "local" is the
        // placeholder the service substitutes anyway.
        api_key: isOllama ? 'local' : apiKey,
        base_url: isCustom || isOllama ? baseUrl : undefined,
        model: isCustom ? model : undefined,
      })
      onConnected()
    } catch (err) {
      const detail = parseApiError(err).detail
      if (
        detail &&
        typeof detail === 'object' &&
        'error_code' in detail
      ) {
        setError(detail as BYOKErrorBody)
        return
      }
      setError({
        error_code: 'network',
        error_message: `Can't reach ${info.name}. Check your internet connection.`,
      })
    }
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <div>
        <h2 className="font-headline text-2xl font-semibold text-on-surface">
          Bring your own key
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
          Pick the provider you already have a key with.
        </p>
      </div>

      <fieldset className="space-y-3">
        <legend className="sr-only">Provider</legend>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {TILES.map((t) => {
            const selected = provider === t.id
            const tileInfo = PROVIDERS[t.id]
            return (
              <button
                key={t.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => {
                  setProvider(t.id)
                  setError(null)
                  if (t.id === 'ollama' && !baseUrl) {
                    setBaseUrl('http://localhost:11434')
                  }
                  if (t.id !== 'ollama' && t.id !== 'custom') {
                    setBaseUrl('')
                  }
                }}
                className={
                  selected
                    ? 'flex h-full flex-col items-start gap-2 rounded-2xl bg-primary-container/60 p-4 text-left text-on-surface ring-2 ring-primary/40 transition'
                    : 'flex h-full flex-col items-start gap-2 rounded-2xl bg-surface-container-high p-4 text-left text-on-surface transition hover:bg-surface-container-highest'
                }
              >
                <span
                  className="material-symbols-outlined text-[22px] text-primary"
                  aria-hidden="true"
                  style={{
                    fontVariationSettings: selected
                      ? "'FILL' 1, 'wght' 500"
                      : "'FILL' 0, 'wght' 500",
                  }}
                >
                  {providerIcon(t.id)}
                </span>
                <span className="font-headline text-sm font-semibold">
                  {tileInfo.name}
                </span>
                <span className="text-xs leading-snug text-on-surface-variant">
                  {t.subtitle}
                </span>
              </button>
            )
          })}
        </div>
        {isOpenAIClass && (
          <p className="text-xs leading-relaxed text-on-surface-variant">
            OpenSec is tuned for Claude. {info.name} should still work, but
            Claude tends to perform better on security reasoning.
          </p>
        )}
      </fieldset>

      <div className="flex items-start gap-3 rounded-2xl bg-surface-container-high px-4 py-3 text-sm leading-relaxed text-on-surface-variant">
        <span
          className="material-symbols-outlined mt-0.5 flex-shrink-0 text-primary"
          aria-hidden="true"
        >
          info
        </span>
        <div className="flex-1 min-w-0">
          <p>{info.blurb}</p>
          {info.consoleUrl && (
            <a
              href={info.consoleUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 rounded-full bg-surface px-3 py-1.5 text-xs font-semibold text-primary hover:bg-surface-container"
            >
              {info.consoleLabel}
              <span className="material-symbols-outlined text-[16px]">
                open_in_new
              </span>
            </a>
          )}
        </div>
      </div>

      {isCustom && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="text-sm font-medium text-on-surface">
              Base URL
            </span>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://my-llm.example/v1"
              className="w-full rounded-xl bg-surface-container-high px-4 py-3 text-sm text-on-surface outline-none focus:bg-surface-container-highest focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-sm font-medium text-on-surface">Model</span>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="llama-3.1-70b"
              className="w-full rounded-xl bg-surface-container-high px-4 py-3 text-sm text-on-surface outline-none focus:bg-surface-container-highest focus:ring-2 focus:ring-primary/30"
            />
          </label>
        </div>
      )}

      {isOllama && (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-on-surface">Base URL</span>
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value)
              setError(null)
            }}
            placeholder="http://localhost:11434"
            className="w-full rounded-xl bg-surface-container-high px-4 py-3 text-sm font-mono text-on-surface outline-none focus:bg-surface-container-highest focus:ring-2 focus:ring-primary/30"
          />
          <p className="text-xs leading-relaxed text-on-surface-variant">
            We probe <span className="font-mono">/api/tags</span> to confirm
            Ollama is reachable. Pick a model from the picker after connecting.
          </p>
          {byok.isPending && (
            <p className="flex items-center gap-2 text-xs text-on-surface-variant">
              <SpinnerIcon className="h-3.5 w-3.5 text-primary" />
              Reaching Ollama…
            </p>
          )}
          {error && (
            <p
              role="alert"
              className="rounded-xl bg-error-container px-4 py-3 text-sm leading-relaxed text-on-error-container"
            >
              {error.error_message}
            </p>
          )}
        </label>
      )}

      {!isOllama && (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-on-surface">API key</span>
          <input
            id="ai-api-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value)
              setError(null)
            }}
            placeholder={info.keyHint ? `${info.keyHint}…` : '…'}
            className="w-full rounded-xl bg-surface-container-high px-4 py-3 text-sm font-mono text-on-surface outline-none focus:bg-surface-container-highest focus:ring-2 focus:ring-primary/30"
          />
          {byok.isPending && (
            <p className="flex items-center gap-2 text-xs text-on-surface-variant">
              <SpinnerIcon className="h-3.5 w-3.5 text-primary" />
              Validating with {info.name}…
            </p>
          )}
          {error && (
            <p
              role="alert"
              className="rounded-xl bg-error-container px-4 py-3 text-sm leading-relaxed text-on-error-container"
            >
              {error.error_message}
            </p>
          )}
        </label>
      )}

      <p className="text-xs leading-relaxed text-on-surface-variant">
        Typical session: $0.05 – $0.20. A $5 top-up at your provider covers
        roughly thirty sessions.
      </p>

      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          Back
        </button>
        <button
          type="submit"
          data-testid="byok-save"
          disabled={!requiredFieldsFilled || byok.isPending}
          className="rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
        >
          {byok.isPending ? 'Validating…' : 'Connect'}
        </button>
      </div>
    </form>
  )
}

function SpinnerIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className ? `${className} animate-spin` : 'animate-spin'}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
