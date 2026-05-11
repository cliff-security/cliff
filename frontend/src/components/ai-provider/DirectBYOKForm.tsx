/**
 * Tier 3 — Direct BYOK form (IMPL-0011 G5).
 *
 * Provider dropdown + deep-linked instructions + password-style input
 * with live validation. Save button stays disabled until validation
 * passes. The "tuned for Claude" subtitle appears for openai + custom.
 */

import { useState } from 'react'
import { useByok, type AIProvider, type BYOKErrorBody } from '@/api/aiProvider'

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
  instructions: string[]
}

const PROVIDERS: Record<AIProvider, ProviderInfo> = {
  anthropic: {
    name: 'Anthropic',
    consoleUrl: 'https://console.anthropic.com/settings/keys',
    consoleLabel: 'Open Anthropic console',
    keyHint: 'sk-ant-',
    instructions: [
      'Visit the Anthropic console → settings → API keys.',
      'Click "Create key" and name it OpenSec.',
      'Paste the key below — it starts with sk-ant-.',
    ],
  },
  openai: {
    name: 'OpenAI',
    consoleUrl: 'https://platform.openai.com/api-keys',
    consoleLabel: 'Open OpenAI console',
    keyHint: 'sk-',
    instructions: [
      'Visit platform.openai.com → API keys.',
      'Click "Create new secret key" and name it OpenSec.',
      'Paste the key below — it starts with sk-.',
    ],
  },
  openrouter: {
    name: 'OpenRouter',
    consoleUrl: 'https://openrouter.ai/keys',
    consoleLabel: 'Open OpenRouter keys',
    keyHint: 'sk-or-',
    instructions: [
      'Visit openrouter.ai → keys.',
      'Generate a new key.',
      'Paste it below.',
    ],
  },
  custom: {
    name: 'Custom (OpenAI-compatible)',
    consoleUrl: '',
    consoleLabel: '',
    keyHint: '',
    instructions: [
      'Use any OpenAI-compatible endpoint.',
      'Provide the base URL and a key.',
      'OpenSec will probe /chat/completions to validate.',
    ],
  },
}

export function DirectBYOKForm({
  initialProvider,
  onConnected,
  onCancel,
}: Props) {
  const [provider, setProvider] = useState<AIProvider>(initialProvider)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [error, setError] = useState<BYOKErrorBody | null>(null)
  const byok = useByok()

  const info = PROVIDERS[provider]
  const isOpenAIClass = provider === 'openai' || provider === 'custom'

  const requiredFieldsFilled =
    apiKey.length >= 4 &&
    (provider !== 'custom' || (baseUrl.length > 0 && model.length > 0))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await byok.mutateAsync({
        provider,
        api_key: apiKey,
        base_url: provider === 'custom' ? baseUrl : undefined,
        model: provider === 'custom' ? model : undefined,
      })
      onConnected()
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      const match = msg.match(/^\d+:\s*(.*)$/s)
      if (match) {
        try {
          const body = JSON.parse(match[1])
          if (body?.detail?.error_code) {
            setError(body.detail as BYOKErrorBody)
            return
          }
        } catch {
          // fall through
        }
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
          Paste your API key
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
          Already have a key with a provider? Drop it in.
        </p>
      </div>

      <div className="space-y-2">
        <label
          htmlFor="ai-provider"
          className="text-sm font-medium text-on-surface"
        >
          Provider
        </label>
        <select
          id="ai-provider"
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value as AIProvider)
            setError(null)
          }}
          className="w-full rounded-xl bg-surface-container px-4 py-3 text-sm text-on-surface outline-none focus:bg-surface-container-high"
        >
          <option value="anthropic">Anthropic</option>
          <option value="openai">OpenAI</option>
          <option value="custom">Custom (OpenAI-compatible)</option>
        </select>
        {isOpenAIClass && (
          <p className="text-xs leading-relaxed text-on-surface-variant">
            OpenSec is tuned for Claude. Your choice should still work, but
            Claude tends to perform better on security reasoning.
          </p>
        )}
      </div>

      <div className="rounded-2xl bg-surface-container p-5 text-sm leading-relaxed text-on-surface-variant">
        <p className="font-medium text-on-surface">How to get your key</p>
        <ol className="mt-2 space-y-1 pl-5 list-decimal">
          {info.instructions.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {info.consoleUrl && (
          <a
            href={info.consoleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
          >
            {info.consoleLabel} →
          </a>
        )}
      </div>

      {provider === 'custom' && (
        <div className="space-y-2">
          <label
            htmlFor="ai-base-url"
            className="text-sm font-medium text-on-surface"
          >
            Base URL
          </label>
          <input
            id="ai-base-url"
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://my-llm.example/v1"
            className="w-full rounded-xl bg-surface-container px-4 py-3 text-sm text-on-surface outline-none focus:bg-surface-container-high"
          />
          <label
            htmlFor="ai-model"
            className="text-sm font-medium text-on-surface"
          >
            Model
          </label>
          <input
            id="ai-model"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="llama-3.1-70b"
            className="w-full rounded-xl bg-surface-container px-4 py-3 text-sm text-on-surface outline-none focus:bg-surface-container-high"
          />
        </div>
      )}

      <div className="space-y-2">
        <label
          htmlFor="ai-api-key"
          className="text-sm font-medium text-on-surface"
        >
          API key
        </label>
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
          className="w-full rounded-xl bg-surface-container px-4 py-3 text-sm font-mono text-on-surface outline-none focus:bg-surface-container-high"
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
      </div>

      <p className="rounded-2xl bg-surface-container px-4 py-3 text-xs leading-relaxed text-on-surface-variant">
        Typical OpenSec workspace run: five to twenty cents. Add five
        dollars to your provider account for roughly thirty sessions.
      </p>

      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container"
        >
          Cancel
        </button>
        <button
          type="submit"
          data-testid="byok-save"
          disabled={!requiredFieldsFilled || byok.isPending}
          className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-60"
        >
          {byok.isPending ? 'Validating…' : 'Save'}
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
