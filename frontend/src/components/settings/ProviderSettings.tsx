import { useEffect, useState, useMemo } from 'react'
import {
  useHealth,
  useModelConfig,
  useUpdateModel,
  useProviders,
  useApiKeys,
  useSetApiKey,
  useDeleteApiKey,
  useConfiguredProviders,
} from '@/api/hooks'
import { useProviderTest } from '@/api/providers'
import type { ProviderTestErrorCode } from '@/api/providers'
import type { ProviderInfo } from '@/api/client'

export default function ProviderSettings() {
  const { data: health } = useHealth()
  const { data: modelConfig } = useModelConfig()
  const { data: providers, isLoading: providersLoading } = useProviders()
  const { data: apiKeys } = useApiKeys()
  const { data: configuredProviders } = useConfiguredProviders()
  const updateModel = useUpdateModel()
  const setApiKey = useSetApiKey()
  const deleteApiKey = useDeleteApiKey()

  const [searchQuery, setSearchQuery] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [editingKeyFor, setEditingKeyFor] = useState<string | null>(null)
  const [deletingKeyFor, setDeletingKeyFor] = useState<string | null>(null)

  const currentModel = modelConfig?.model_full_id || health?.model || ''
  const currentProviderId = currentModel.split('/')[0] || ''
  const currentModelId = currentModel.split('/').slice(1).join('/') || ''

  const providerList = useMemo(() => (providers || []) as ProviderInfo[], [providers])
  const storedKeyMap = new Map((apiKeys || []).map((k) => [k.provider, k]))

  // Build a set of providers that have active credentials (from env vars or config)
  const activeAuthProviders = useMemo(() => {
    const set = new Set<string>()
    // The API returns { providers: { providers: [...] } } — unwrap the nested structure
    const raw = configuredProviders?.providers
    const list = Array.isArray(raw) ? raw : (raw as Record<string, unknown>)?.providers
    if (Array.isArray(list)) {
      for (const p of list) {
        if (p.key || p.source === 'env' || p.source === 'config') {
          set.add(p.id)
        }
      }
    }
    return set
  }, [configuredProviders])

  // Find the active provider
  const activeProvider = providerList.find((p) => p.id === currentProviderId)
  const activeNeedsKey = activeProvider ? activeProvider.env.length > 0 : false

  // Determine auth source label for a provider
  const getAuthLabel = (providerId: string) => {
    const stored = storedKeyMap.get(providerId)
    if (stored) return { text: stored.key_masked, source: 'stored' as const }
    if (activeAuthProviders.has(providerId)) return { text: 'Configured via environment', source: 'env' as const }
    return null
  }

  // Search results — provider matches always rank above model-only matches.
  // Without this, gateway providers (OpenRouter, etc.) whose model IDs contain
  // "anthropic" or "openai" can crowd out the actual canonical provider.
  const searchResults = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return []

    type Hit = {
      provider: ProviderInfo
      matchingModels: [string, ProviderInfo['models'][string]][]
      providerMatch: boolean
    }
    const tierPrefix: Hit[] = []
    const tierSubstring: Hit[] = []
    const tierModelOnly: Hit[] = []

    for (const provider of providerList) {
      const idLower = provider.id.toLowerCase()
      const nameLower = provider.name.toLowerCase()
      const isPrefixMatch = idLower.startsWith(q) || nameLower.startsWith(q)
      const isSubstringMatch = !isPrefixMatch && (idLower.includes(q) || nameLower.includes(q))
      const providerMatch = isPrefixMatch || isSubstringMatch

      const matchingModels = Object.entries(provider.models).filter(
        ([id, model]) =>
          id.toLowerCase().includes(q) ||
          (model.name && model.name.toLowerCase().includes(q)),
      )

      if (providerMatch) {
        const hit: Hit = {
          provider,
          matchingModels: Object.entries(provider.models),
          providerMatch: true,
        }
        if (isPrefixMatch) tierPrefix.push(hit)
        else tierSubstring.push(hit)
      } else if (matchingModels.length > 0) {
        tierModelOnly.push({ provider, matchingModels, providerMatch: false })
      }
    }

    const byName = (a: Hit, b: Hit) => a.provider.name.localeCompare(b.provider.name)
    tierPrefix.sort(byName)
    tierSubstring.sort(byName)
    tierModelOnly.sort(byName)

    return [...tierPrefix, ...tierSubstring, ...tierModelOnly.slice(0, 8)]
  }, [searchQuery, providerList])

  const handleSelectModel = (fullId: string) => {
    updateModel.mutate(fullId)
    setSearchQuery('')
  }

  const handleSaveKey = (providerId: string) => {
    if (!keyInput.trim()) return
    setApiKey.mutate(
      { provider: providerId, key: keyInput.trim() },
      {
        onSuccess: () => {
          setKeyInput('')
          setEditingKeyFor(null)
        },
      },
    )
  }

  const handleDeleteKey = (providerId: string) => {
    deleteApiKey.mutate(providerId, {
      onSuccess: () => setDeletingKeyFor(null),
    })
  }

  // Reusable inline auth row
  const renderAuthRow = (providerId: string, provider: ProviderInfo) => {
    const needsKey = provider.env.length > 0
    if (!needsKey) return null

    const auth = getAuthLabel(providerId)
    const isEnvBased = auth?.source === 'env'

    if (deletingKeyFor === providerId) {
      return (
        <div className="bg-surface-container-low rounded-lg px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-on-surface-variant flex-1">Remove this API key?</span>
            <button
              onClick={() => handleDeleteKey(providerId)}
              disabled={deleteApiKey.isPending}
              className="px-3 py-1.5 bg-error text-on-error rounded-md text-xs font-semibold"
            >
              Remove
            </button>
            <button
              onClick={() => setDeletingKeyFor(null)}
              className="px-3 py-1.5 text-on-surface-variant hover:text-on-surface rounded-md text-xs"
            >
              Cancel
            </button>
          </div>
        </div>
      )
    }

    if (editingKeyFor === providerId) {
      return (
        <div className="bg-surface-container-low rounded-lg px-4 py-3">
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Enter API key"
              className="flex-1 bg-surface-container-lowest rounded-md px-3 py-1.5 text-xs font-mono outline-none focus:ring-2 focus:ring-primary/20"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveKey(providerId)
                if (e.key === 'Escape') { setEditingKeyFor(null); setKeyInput('') }
              }}
            />
            <button
              onClick={() => handleSaveKey(providerId)}
              disabled={!keyInput.trim() || setApiKey.isPending}
              className="px-3 py-1.5 bg-primary text-on-primary rounded-md text-xs font-semibold disabled:opacity-40"
            >
              {setApiKey.isPending ? '...' : 'Save'}
            </button>
            <button
              onClick={() => { setEditingKeyFor(null); setKeyInput('') }}
              className="px-3 py-1.5 text-on-surface-variant hover:text-on-surface rounded-md text-xs"
            >
              Cancel
            </button>
          </div>
        </div>
      )
    }

    return (
      <div className="bg-surface-container-low rounded-lg px-4 py-3">
        <div className="flex items-center justify-between mb-1">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
            Authentication
          </label>
          <span className="text-[11px] font-mono text-on-surface-variant/50">
            {provider.env.join(', ')}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${auth ? 'bg-green-500' : 'bg-error/60'}`} />
          {auth ? (
            <>
              <span className="text-xs font-mono text-on-surface-variant">
                {isEnvBased ? (
                  <span className="flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-xs text-green-600">lock</span>
                    {auth.text}
                  </span>
                ) : (
                  auth.text
                )}
              </span>
              {!isEnvBased && (
                <>
                  <button
                    onClick={() => { setEditingKeyFor(providerId); setKeyInput('') }}
                    className="ml-auto px-2.5 py-1 text-primary hover:bg-primary/5 rounded-md text-xs font-semibold transition-colors"
                  >
                    Update
                  </button>
                  <button
                    onClick={() => setDeletingKeyFor(providerId)}
                    className="p-1 text-on-surface-variant hover:text-error rounded-md transition-colors"
                    title="Remove key"
                  >
                    <span className="material-symbols-outlined text-sm">delete</span>
                  </button>
                </>
              )}
              {isEnvBased && (
                <button
                  onClick={() => { setEditingKeyFor(providerId); setKeyInput('') }}
                  className="ml-auto px-2.5 py-1 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest rounded-md text-xs transition-colors"
                >
                  Override
                </button>
              )}
            </>
          ) : (
            <>
              <span className="text-xs text-on-surface-variant">No key configured</span>
              <button
                onClick={() => { setEditingKeyFor(providerId); setKeyInput('') }}
                className="ml-auto px-2.5 py-1 bg-primary text-on-primary rounded-md text-xs font-semibold hover:bg-primary/90 transition-colors"
              >
                Set key
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <section id="providers">
      <div className="mb-8">
        <h2 className="text-2xl font-bold tracking-tight text-on-surface mb-2">
          Providers
        </h2>
        <p className="text-on-surface-variant text-sm max-w-xl">
          Configure your AI provider, model, and authentication.
          Changes take effect immediately.
        </p>
      </div>

      <div className="space-y-4">
        {/* ── Active provider + model card ── */}
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm shadow-slate-200/50 space-y-4">
          <div className="flex items-center gap-2 mb-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Active configuration
            </label>
            <span
              className={`w-2 h-2 rounded-full ${
                health?.opencode === 'ok' ? 'bg-green-500' : 'bg-outline-variant'
              }`}
            />
            <span className="text-[11px] text-on-surface-variant">
              {health?.opencode === 'ok' ? 'Running' : 'Unavailable'}
              {health?.opencode_version && ` \u00b7 v${health.opencode_version}`}
            </span>
          </div>

          {/* Provider + Model display */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant block mb-1.5">
                Provider
              </label>
              <div className="bg-surface-container-low rounded-lg px-4 py-2.5 text-sm font-semibold text-on-surface">
                {activeProvider?.name || currentProviderId || 'Not configured'}
              </div>
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant block mb-1.5">
                Model
              </label>
              <div className="bg-surface-container-low rounded-lg px-4 py-2.5 text-sm font-mono text-on-surface">
                {currentModelId || 'Not configured'}
              </div>
            </div>
          </div>

          {/* Auth status for active provider */}
          {activeNeedsKey && activeProvider && renderAuthRow(currentProviderId, activeProvider)}

          {/* Test connection — PRD-0004 Story 4 / IMPL-0004 T12 */}
          <TestConnectionRow
            currentModel={currentModel}
            currentProviderId={currentProviderId}
            providerList={providerList}
          />

          {updateModel.isSuccess && (
            <p className="text-xs text-green-600 flex items-center gap-1">
              <span className="material-symbols-outlined text-sm">check_circle</span>
              Model updated
            </p>
          )}
          {updateModel.isError && (
            <p className="text-xs text-error flex items-center gap-1">
              <span className="material-symbols-outlined text-sm">error</span>
              {(updateModel.error as Error)?.message || 'Failed to update model'}
            </p>
          )}

          <p className="text-[11px] text-on-surface-variant/60 flex items-center gap-1">
            <span className="material-symbols-outlined text-[12px]">info</span>
            Model changes apply to new workspaces. Existing workspaces keep their original model.
          </p>
        </div>

        {/* ── Search for different provider / model ── */}
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm shadow-slate-200/50">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant block mb-2">
            Change provider or model
          </label>
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant/50 text-lg">
              search
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search providers or models (e.g. anthropic, gpt-4, claude...)"
              className="w-full bg-surface-container-low rounded-lg pl-10 pr-4 py-3 text-sm text-on-surface placeholder:text-on-surface-variant/40 outline-none focus:ring-2 focus:ring-primary/20"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant/50 hover:text-on-surface-variant"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            )}
          </div>

          {/* Search results — all auto-expanded with models visible */}
          {searchQuery.trim() && (
            <div className="mt-3 space-y-2">
              {providersLoading ? (
                <p className="text-xs text-on-surface-variant py-2">Loading...</p>
              ) : searchResults.length === 0 ? (
                <p className="text-xs text-on-surface-variant py-2">
                  No providers or models match "{searchQuery}"
                </p>
              ) : (
                searchResults.map(({ provider, matchingModels, providerMatch }) => {
                  const needsKey = provider.env.length > 0
                  const auth = getAuthLabel(provider.id)
                  const isCurrentProvider = provider.id === currentProviderId

                  return (
                    <div
                      key={provider.id}
                      className={`rounded-lg overflow-hidden ${
                        isCurrentProvider
                          ? 'ring-1 ring-primary/20 bg-primary/[0.02]'
                          : 'bg-surface-container-low'
                      }`}
                    >
                      {/* Provider header */}
                      <div className="flex items-center gap-3 px-4 py-2.5">
                        {needsKey && (
                          <span
                            className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                              auth ? 'bg-green-500' : 'bg-error/60'
                            }`}
                          />
                        )}
                        <span className="text-sm font-semibold text-on-surface flex-1">
                          {provider.name}
                          {providerMatch && !isCurrentProvider && (
                            <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant bg-surface-container-highest px-1.5 py-0.5 rounded">
                              provider
                            </span>
                          )}
                          {isCurrentProvider && (
                            <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                              active
                            </span>
                          )}
                        </span>
                        {needsKey && auth && (
                          <span className="text-[11px] font-mono text-on-surface-variant/50">
                            {auth.source === 'env' ? (
                              <span className="flex items-center gap-1">
                                <span className="material-symbols-outlined text-[11px] text-green-600">lock</span>
                                env
                              </span>
                            ) : auth.text}
                          </span>
                        )}
                        {needsKey && !auth && (
                          <button
                            onClick={() => { setEditingKeyFor(provider.id); setKeyInput('') }}
                            className="text-[11px] text-primary font-semibold hover:bg-primary/5 px-2 py-0.5 rounded transition-colors"
                          >
                            Set key
                          </button>
                        )}
                      </div>

                      {/* Inline key editor if active */}
                      {editingKeyFor === provider.id && (
                        <div className="px-4 pb-2">
                          <div className="bg-surface-container-lowest rounded-md px-3 py-2 flex items-center gap-2">
                            <input
                              type="password"
                              value={keyInput}
                              onChange={(e) => setKeyInput(e.target.value)}
                              placeholder="Enter API key"
                              className="flex-1 bg-surface-container-low rounded-md px-3 py-1.5 text-xs font-mono outline-none focus:ring-2 focus:ring-primary/20"
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveKey(provider.id)
                                if (e.key === 'Escape') { setEditingKeyFor(null); setKeyInput('') }
                              }}
                            />
                            <button
                              onClick={() => handleSaveKey(provider.id)}
                              disabled={!keyInput.trim() || setApiKey.isPending}
                              className="px-3 py-1.5 bg-primary text-on-primary rounded-md text-xs font-semibold disabled:opacity-40"
                            >
                              {setApiKey.isPending ? '...' : 'Save'}
                            </button>
                            <button
                              onClick={() => { setEditingKeyFor(null); setKeyInput('') }}
                              className="text-xs text-on-surface-variant hover:text-on-surface"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Models — always visible in search results */}
                      <div className="px-4 pb-3">
                        <div className="flex flex-wrap gap-1.5">
                          {matchingModels.map(([modelId, model]) => {
                            const fullId = `${provider.id}/${modelId}`
                            const isActive = fullId === currentModel
                            return (
                              <button
                                key={modelId}
                                onClick={() => handleSelectModel(fullId)}
                                disabled={updateModel.isPending || isActive}
                                className={`px-3 py-1.5 rounded-md text-xs font-mono transition-all ${
                                  isActive
                                    ? 'bg-primary text-on-primary shadow-sm'
                                    : 'bg-surface-container-lowest text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest'
                                } disabled:opacity-60`}
                              >
                                {model.name || modelId}
                                {model.reasoning && (
                                  <span className="ml-1 opacity-60" title="Reasoning">R</span>
                                )}
                                {model.tool_call && (
                                  <span className="ml-0.5 opacity-60" title="Tool use">T</span>
                                )}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Test connection row (PRD-0004 Story 4 / IMPL-0004 T12)
// ---------------------------------------------------------------------------

interface TestConnectionRowProps {
  currentModel: string
  currentProviderId: string
  providerList: ProviderInfo[]
}

function TestConnectionRow({
  currentModel,
  currentProviderId,
  providerList,
}: TestConnectionRowProps) {
  const probe = useProviderTest()
  const result = probe.data ?? null

  // Clear stale results when the model changes out from under us.
  useEffect(() => {
    probe.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentModel])

  const disabled = !currentModel || probe.isPending

  return (
    <div className="bg-surface-container-low rounded-lg px-4 py-3 flex flex-wrap items-center gap-3">
      <div className="flex flex-col gap-0.5 min-w-[10rem]">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
          Connection check
        </span>
        <span className="text-[11px] text-on-surface-variant/70">
          Sends a tiny probe through OpenCode (≤ 8s, ≤ $0.001).
        </span>
      </div>
      <button
        type="button"
        data-testid="test-connection-button"
        disabled={disabled}
        onClick={() => probe.mutate({})}
        aria-busy={probe.isPending}
        aria-describedby="test-connection-result"
        className="inline-flex items-center gap-1.5 rounded-full bg-surface-container-highest px-4 py-1.5 text-xs font-semibold text-on-surface hover:bg-surface-container-high disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      >
        {probe.isPending ? (
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
        ) : (
          <span className="material-symbols-outlined text-sm" aria-hidden>
            bolt
          </span>
        )}
        {probe.isPending ? 'Testing…' : 'Test connection'}
      </button>
      <TestConnectionChip
        result={result}
        currentModel={currentModel}
        currentProviderId={currentProviderId}
        providerList={providerList}
      />
    </div>
  )
}

function TestConnectionChip({
  result,
  currentModel,
  currentProviderId,
  providerList,
}: {
  result: {
    ok: boolean
    latency_ms: number
    error_code: ProviderTestErrorCode | null
    error_message: string | null
  } | null
  currentModel: string
  currentProviderId: string
  providerList: ProviderInfo[]
}) {
  if (!result) {
    return (
      <span
        id="test-connection-result"
        className="text-[11px] text-on-surface-variant/60"
        role="status"
        aria-live="polite"
      >
        No test run yet.
      </span>
    )
  }

  if (result.ok) {
    const latency = (result.latency_ms / 1000).toFixed(1)
    return (
      <span
        id="test-connection-result"
        data-testid="test-connection-chip"
        data-ok="true"
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-1 rounded-full bg-tertiary-container/30 px-3 py-1 text-xs font-semibold text-tertiary"
      >
        <span className="material-symbols-outlined text-sm" aria-hidden>
          check_circle
        </span>
        Connection OK · {latency}s
      </span>
    )
  }

  const message = result.error_message ?? 'Test failed'
  return (
    <div className="flex flex-col gap-1">
      <span
        id="test-connection-result"
        data-testid="test-connection-chip"
        data-ok="false"
        data-error-code={result.error_code ?? 'other'}
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-1 rounded-full bg-error-container/20 px-3 py-1 text-xs font-semibold text-error"
      >
        <span className="material-symbols-outlined text-sm" aria-hidden>
          error
        </span>
        {message}
      </span>
      {result.error_code === 'model_not_found' && (
        <TypoSuggestion
          currentModel={currentModel}
          currentProviderId={currentProviderId}
          providerList={providerList}
        />
      )}
    </div>
  )
}

/**
 * Cheap 1-edit-distance Levenshtein for the "Did you mean `foo`?" hint
 * surfaced on model_not_found (PRD-0004 Story 4 P1 acceptance criterion).
 * Scans the active provider's model catalog only; if no model is within
 * edit distance 2, the hint is silently omitted.
 */
function editDistance(a: string, b: string): number {
  if (a === b) return 0
  if (!a.length) return b.length
  if (!b.length) return a.length
  const prev = new Array(b.length + 1).fill(0).map((_, i) => i)
  for (let i = 1; i <= a.length; i += 1) {
    const curr = [i]
    for (let j = 1; j <= b.length; j += 1) {
      curr.push(
        Math.min(
          prev[j] + 1,
          curr[j - 1] + 1,
          prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
        ),
      )
    }
    for (let j = 0; j < curr.length; j += 1) prev[j] = curr[j]
  }
  return prev[b.length]
}

function TypoSuggestion({
  currentModel,
  currentProviderId,
  providerList,
}: {
  currentModel: string
  currentProviderId: string
  providerList: ProviderInfo[]
}) {
  const currentModelId = currentModel.split('/').slice(1).join('/')
  const activeProvider = providerList.find((p) => p.id === currentProviderId)
  if (!currentModelId || !activeProvider) return null

  let best: { id: string; distance: number } | null = null
  for (const id of Object.keys(activeProvider.models)) {
    const d = editDistance(id, currentModelId)
    if (d <= 2 && d > 0 && (best === null || d < best.distance)) {
      best = { id, distance: d }
    }
  }
  if (!best) return null

  return (
    <p className="text-[11px] text-on-surface-variant">
      Did you mean{' '}
      <code className="font-mono text-on-surface">
        {activeProvider.id}/{best.id}
      </code>
      ?
    </p>
  )
}
