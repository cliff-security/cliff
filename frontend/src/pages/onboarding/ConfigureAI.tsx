import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import OnboardingShell from '@/components/onboarding/OnboardingShell'
import ProviderCard from '@/components/onboarding/ProviderCard'
import WizardNav from '@/components/onboarding/WizardNav'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'
import ModelPickerDialog from '@/components/onboarding/ModelPickerDialog'
import { useProviders, useSetApiKey, useUpdateModel } from '@/api/hooks'
import { useProviderTest } from '@/api/providers'
import { onboardingStorage } from './storage'

/**
 * The short list the wizard surfaces as cards. ``google`` is OpenCode's
 * provider id for Gemini — the user-facing label stays "Gemini". ``other``
 * is a meta-choice that opens the full searchable catalog.
 */
type ProviderChoice = 'openai' | 'anthropic' | 'google' | 'other'

const CARDS: {
  id: ProviderChoice
  name: string
  description: string
  icon: string
}[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-4 class models. Good default for most maintainers.',
    icon: 'auto_awesome',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude models. Excellent at careful reasoning.',
    icon: 'psychology',
  },
  {
    id: 'google',
    name: 'Gemini',
    description: "Google's multimodal models with large context windows.",
    icon: 'hub',
  },
  {
    id: 'other',
    name: 'Other',
    description: 'Pick any model from the full catalog.',
    icon: 'more_horiz',
  },
]

interface Selection {
  provider: string
  model: string
}

// Two-stage button state (PRD-0006 follow-up).
//
// The original "Test and continue" button only saved the key — it never
// actually probed the provider, so a wrong key sailed through and surfaced
// later as a confusing agent failure. We now require an explicit
// successful probe before the wizard advances. ``passed`` collapses the
// CTA to a plain "Continue" so the second click is fast.
type TestStatus = 'untested' | 'testing' | 'passed' | 'failed'

interface TestPass {
  /** Latency the backend reported, surfaced in the success badge so the
   *  user knows we actually round-tripped to the provider. */
  latencyMs: number
}

export default function ConfigureAI() {
  const navigate = useNavigate()
  const { data: providers } = useProviders()
  const updateModel = useUpdateModel()
  const setApiKey = useSetApiKey()
  const providerTest = useProviderTest()

  const [providerId, setProviderId] = useState<ProviderChoice>('openai')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [apiKey, setApiKeyInput] = useState('')
  const [otherOpen, setOtherOpen] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [allowBypass, setAllowBypass] = useState(false)
  const [testStatus, setTestStatus] = useState<TestStatus>('untested')
  const [testPass, setTestPass] = useState<TestPass | null>(null)

  // Reset the test verdict whenever the user changes anything that could
  // have made it valid. We do NOT clear the saved key — it's still in the
  // vault from the previous attempt, but the user has to re-prove it.
  function resetTest() {
    setTestStatus('untested')
    setTestPass(null)
    setErrorMsg(null)
    setAllowBypass(false)
  }

  // Models available for the short-list providers. "Other" always opens the
  // picker — we never need a local model list for it.
  const modelsForProvider = useMemo(() => {
    if (!providers || providerId === 'other') return []
    const p = providers.find((x) => x.id === providerId)
    if (!p) return []
    return Object.entries(p.models).map(([id, m]) => ({
      id,
      name: m.name || id,
    }))
  }, [providers, providerId])

  function handleCardSelect(id: ProviderChoice) {
    setProviderId(id)
    setSelection(null)
    resetTest()
    if (id === 'other') setOtherOpen(true)
  }

  function handleOtherPick(provider: string, model: string) {
    setSelection({ provider, model })
    setProviderId('other')
    setOtherOpen(false)
    resetTest()
  }

  function advance(selected: Selection) {
    onboardingStorage.set('provider', selected.provider)
    onboardingStorage.set('model', selected.model)
    navigate('/onboarding/start')
  }

  /**
   * First-click handler: saves the credentials, then probes the provider
   * via ``/api/settings/providers/test``. The probe fires a bounded
   * "Say OK" through the just-saved configuration, so save MUST happen
   * first — otherwise we'd be testing whatever was previously set.
   *
   * On any failure (save or probe) we surface ``error_message`` from the
   * backend and offer the existing "Save anyway" bypass for genuinely
   * stuck users (e.g. air-gapped environments where the probe can't run).
   */
  async function handleTest() {
    if (!selection || !apiKey.trim()) return
    setErrorMsg(null)
    setAllowBypass(false)
    setTestStatus('testing')

    const fullId = `${selection.provider}/${selection.model}`
    try {
      await setApiKey.mutateAsync({ provider: selection.provider, key: apiKey.trim() })
      await updateModel.mutateAsync(fullId)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Couldn't save your choice"
      setErrorMsg(msg)
      setAllowBypass(true)
      setTestStatus('failed')
      return
    }

    try {
      const result = await providerTest.mutateAsync({
        provider: selection.provider,
        model: selection.model,
        api_key: apiKey.trim(),
      })
      if (result.ok) {
        setTestPass({ latencyMs: result.latency_ms })
        setTestStatus('passed')
      } else {
        setErrorMsg(result.error_message || 'The provider rejected the request.')
        setAllowBypass(true)
        setTestStatus('failed')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not reach the provider.'
      setErrorMsg(msg)
      setAllowBypass(true)
      setTestStatus('failed')
    }
  }

  function handleAdvance() {
    if (!selection) return
    advance(selection)
  }

  function handleSaveAnyway() {
    if (!selection) return
    advance(selection)
  }

  const saving = setApiKey.isPending || updateModel.isPending
  const testing = testStatus === 'testing' || providerTest.isPending || saving
  const inputsReady = !!selection && apiKey.trim().length > 0
  const passed = testStatus === 'passed'

  // The CTA is the same physical button across both stages — only its
  // label and handler change. Keeping it in the same DOM slot avoids
  // jumpy layout when the verdict comes back.
  const ctaLabel = testing
    ? 'Testing…'
    : passed
      ? 'Continue'
      : 'Test connection'
  const ctaHandler = passed ? handleAdvance : handleTest
  const ctaDisabled = !inputsReady || testing

  return (
    <OnboardingShell step={2}>
      <h1 className="font-headline text-3xl font-extrabold text-on-surface mb-2">
        Configure your AI model
      </h1>
      <p className="text-on-surface-variant mb-8">
        OpenSec uses your model to explain findings and draft fixes. Pick a
        provider, then pick a model. You can change this later in Settings.
      </p>

      <div
        role="radiogroup"
        aria-label="AI provider"
        className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8"
      >
        {CARDS.map((p) => (
          <ProviderCard
            key={p.id}
            provider={p}
            selected={providerId === p.id}
            onSelect={handleCardSelect}
          />
        ))}
      </div>

      {providerId !== 'other' && (
        <label className="block mb-5">
          <span className="block text-sm font-semibold text-on-surface mb-2">
            Model <span className="text-error">*</span>
          </span>
          <select
            value={selection?.provider === providerId ? selection.model : ''}
            onChange={(e) => {
              const modelId = e.target.value
              if (!modelId) {
                setSelection(null)
              } else {
                setSelection({ provider: providerId, model: modelId })
              }
              resetTest()
            }}
            className="w-full px-4 py-3 rounded-lg bg-surface-container-lowest shadow-sm border-0 ring-0 focus:ring-2 focus:ring-primary/30 focus:outline-none text-sm"
          >
            <option value="">
              {modelsForProvider.length
                ? 'Pick a model…'
                : 'Loading model catalog…'}
            </option>
            {modelsForProvider.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {providerId === 'other' && (
        <div className="mb-5 rounded-lg bg-surface-container-lowest shadow-sm px-4 py-3 flex items-center gap-3">
          <span className="material-symbols-outlined text-on-surface-variant">
            more_horiz
          </span>
          <div className="flex-1 text-sm">
            {selection ? (
              <>
                <span className="text-on-surface-variant">Selected:</span>{' '}
                <span className="font-mono font-semibold text-on-surface">
                  {selection.provider}/{selection.model}
                </span>
              </>
            ) : (
              <span className="text-on-surface-variant">
                No model picked yet — open the catalog to choose one.
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setOtherOpen(true)}
            className="text-xs font-semibold text-primary hover:underline px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            {selection ? 'Change' : 'Open catalog'}
          </button>
        </div>
      )}

      <label className="block mb-5">
        <span className="block text-sm font-semibold text-on-surface mb-2">
          API key <span className="text-error">*</span>
        </span>
        <input
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => {
            setApiKeyInput(e.target.value)
            resetTest()
          }}
          placeholder="sk-••••••••••••••••••••••••••••"
          className="w-full px-4 py-3 rounded-lg bg-surface-container-lowest shadow-sm border-0 ring-0 focus:ring-2 focus:ring-primary/30 focus:outline-none text-sm font-mono"
        />
      </label>

      <div className="flex items-start gap-3 rounded-xl bg-primary-container/30 px-5 py-4">
        <span
          className="material-symbols-outlined text-primary mt-0.5"
          aria-hidden="true"
        >
          shield
        </span>
        <p className="text-sm text-on-primary-container leading-relaxed">
          Your key is encrypted on disk in the local credential vault. It never
          travels to OpenSec servers — agents talk directly to your chosen
          provider.
        </p>
      </div>

      {errorMsg && (
        <InlineErrorCallout
          title="We couldn't verify that key"
          body={
            <>
              {errorMsg}
              {allowBypass && (
                <>
                  {' '}
                  <button
                    type="button"
                    onClick={handleSaveAnyway}
                    className="font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded"
                  >
                    Save anyway and continue
                  </button>
                  .
                </>
              )}
            </>
          }
        />
      )}

      {passed && (
        <div
          role="status"
          aria-live="polite"
          data-testid="provider-test-pass"
          className="mt-4 rounded-lg bg-tertiary-container/30 px-4 py-3 flex items-start gap-3"
        >
          <span
            className="material-symbols-outlined text-tertiary flex-shrink-0"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            check_circle
          </span>
          <div className="text-sm text-on-surface">
            <p className="font-semibold">Connection verified</p>
            <p className="text-on-surface-variant mt-0.5">
              {selection
                ? `${selection.provider}/${selection.model} responded in ${testPass?.latencyMs ?? '—'} ms.`
                : 'Provider responded.'}
            </p>
          </div>
        </div>
      )}

      <WizardNav
        onBack={() => navigate('/onboarding/connect')}
        onNext={ctaHandler}
        nextLabel={ctaLabel}
        nextDisabled={ctaDisabled}
      />

      <ModelPickerDialog
        open={otherOpen}
        onClose={() => setOtherOpen(false)}
        onSelect={handleOtherPick}
      />
    </OnboardingShell>
  )
}
