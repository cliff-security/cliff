import { useState } from 'react'
import {
  useIntegrations,
  useCreateIntegration,
  useDeleteIntegration,
  useUpdateIntegration,
  useRegistry,
  useCredentials,
  useStoreCredential,
  useTestIntegration,
  useAllIntegrationsHealth,
} from '@/api/hooks'
import {
  useGithubAppDisconnect,
  useGithubAppResumeOnReturn,
} from '@/api/githubApp'
import type {
  RegistryEntry,
  CredentialField,
  IntegrationConfigItem,
  IntegrationHealthStatus,
} from '@/api/client'
import { GithubAppConnectButton } from './GithubAppConnectButton'
import { GithubAppDeviceFlowModal } from './GithubAppDeviceFlowModal'
import { GithubAppMigrationBanner } from './GithubAppMigrationBanner'

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

type HealthLevel = 'ok' | 'warn' | 'error' | 'unknown'

function resolveHealthLevel(health: IntegrationHealthStatus | undefined): HealthLevel {
  if (!health) return 'unknown'
  if (health.credential_status !== 'ok') return 'error'
  if (health.connection_status === 'ok') return 'ok'
  if (health.connection_status === 'unchecked') return 'warn'
  return 'error'
}

function healthLabel(health: IntegrationHealthStatus | undefined, level: HealthLevel): string {
  if (!health || level === 'unknown') return 'Not checked'
  if (level === 'ok') return 'Connected'
  if (level === 'warn') return 'Credentials ok'
  // Error states
  if (health.credential_status === 'missing') return 'No credentials'
  if (health.credential_status === 'decrypt_error') return 'Key error'
  return health.error_message || 'Connection failed'
}

const DOT_STYLES: Record<HealthLevel, string> = {
  ok: 'bg-green-500',
  warn: 'bg-amber-400',
  error: 'bg-error',
  unknown: 'bg-outline-variant',
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  if (status === 'available') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
        Available
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-on-surface-variant bg-surface-container-low px-2 py-0.5 rounded-full">
      Coming soon
    </span>
  )
}

// ---------------------------------------------------------------------------
// Health indicator (dot + label + timestamp)
// ---------------------------------------------------------------------------

function HealthIndicator({ health }: { health: IntegrationHealthStatus | undefined }) {
  const level = resolveHealthLevel(health)
  const label = healthLabel(health, level)
  const ago = timeAgo(health?.last_checked ?? null)

  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="relative flex h-2 w-2 flex-shrink-0">
        {level === 'ok' && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-40" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${DOT_STYLES[level]}`} />
      </span>
      <span
        className={`text-xs font-medium truncate ${
          level === 'error' ? 'text-error' : 'text-on-surface-variant'
        }`}
      >
        {label}
      </span>
      {ago && (
        <span className="text-[10px] text-outline-variant flex-shrink-0">{ago}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Credential form (dynamic from credentials_schema)
// ---------------------------------------------------------------------------

function CredentialForm({
  entry,
  integrationId,
  integration,
  onDone,
}: {
  entry: RegistryEntry
  integrationId: string
  integration?: IntegrationConfigItem | null
  onDone: () => void
}) {
  const storeCredential = useStoreCredential()
  const updateIntegration = useUpdateIntegration()
  const testIntegration = useTestIntegration()
  const [values, setValues] = useState<Record<string, string>>({})
  const [configValues, setConfigValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const field of entry.config_fields ?? []) {
      const existing = integration?.config?.[field.key_name]
      if (typeof existing === 'string') initial[field.key_name] = existing
    }
    return initial
  })
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const handleSaveAndTest = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      // Store each credential in vault
      for (const field of entry.credentials_schema) {
        const val = values[field.key_name]
        if (val && val.trim()) {
          await storeCredential.mutateAsync({
            integrationId,
            keyName: field.key_name,
            value: val.trim(),
          })
        }
      }
      // Store config fields in integration config
      const configFields = entry.config_fields ?? []
      if (configFields.length > 0) {
        const existingConfig = integration?.config ?? {}
        const mergedConfig = { ...existingConfig }
        for (const field of configFields) {
          const val = configValues[field.key_name]
          if (val !== undefined) mergedConfig[field.key_name] = val
        }
        await updateIntegration.mutateAsync({
          id: integrationId,
          data: { config: mergedConfig },
        })
      }
      // Test connection
      const result = await testIntegration.mutateAsync(integrationId)
      setTestResult(result)
    } catch (err) {
      setTestResult({ success: false, message: String(err) })
    } finally {
      setSaving(false)
    }
  }

  const allRequiredFilled = entry.credentials_schema
    .filter((f) => f.required)
    .every((f) => values[f.key_name]?.trim())

  const renderField = (field: CredentialField, value: string, onChange: (v: string) => void) => (
    <div key={field.key_name}>
      <label className="text-xs font-semibold text-on-surface-variant block mb-1">
        {field.label}
        {field.required && <span className="text-error ml-0.5">*</span>}
      </label>
      <input
        type={field.type === 'password' ? 'password' : 'text'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder || ''}
        className="w-full bg-surface-container-lowest rounded-md px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20"
      />
      {field.help_text && (
        <p className="text-xs text-on-surface-variant mt-1">{field.help_text}</p>
      )}
    </div>
  )

  return (
    <div className="space-y-4">
      {entry.credentials_schema.map((field: CredentialField) =>
        renderField(field, values[field.key_name] || '', (v) =>
          setValues({ ...values, [field.key_name]: v }),
        ),
      )}

      {(entry.config_fields ?? []).length > 0 && (
        <>
          <h4 className="text-sm font-semibold text-on-surface mt-2">Configuration</h4>
          {(entry.config_fields ?? []).map((field: CredentialField) =>
            renderField(field, configValues[field.key_name] || '', (v) =>
              setConfigValues({ ...configValues, [field.key_name]: v }),
            ),
          )}
        </>
      )}

      {testResult && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            testResult.success
              ? 'bg-green-50 text-green-800'
              : 'bg-red-50 text-red-800'
          }`}
        >
          <span className="material-symbols-outlined text-base align-text-bottom mr-1">
            {testResult.success ? 'check_circle' : 'error'}
          </span>
          {testResult.message}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleSaveAndTest}
          disabled={!allRequiredFilled || saving}
          className="px-4 py-2 bg-primary text-on-primary rounded-md text-sm font-semibold disabled:opacity-40 transition-colors hover:bg-primary/90"
        >
          {saving ? 'Saving...' : 'Save & test'}
        </button>
        <button
          onClick={onDone}
          className="px-4 py-2 text-on-surface-variant hover:text-on-surface rounded-md text-sm transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Setup panel (slide-in for a single registry entry)
// ---------------------------------------------------------------------------

function SetupPanel({
  entry,
  integrationId,
  integration,
  onClose,
}: {
  entry: RegistryEntry
  integrationId: string | null
  integration?: IntegrationConfigItem | null
  onClose: () => void
}) {
  const createIntegration = useCreateIntegration()
  const [createdId, setCreatedId] = useState<string | null>(integrationId)

  const handleCreate = async () => {
    const result = await createIntegration.mutateAsync({
      adapter_type: entry.adapter_type,
      provider_name: entry.name,
    })
    setCreatedId(result.id)
  }

  return (
    <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm shadow-slate-200/50 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-surface-container-low flex items-center justify-center">
            <span className="material-symbols-outlined text-xl text-on-surface-variant">
              {entry.icon}
            </span>
          </div>
          <div>
            <h3 className="text-lg font-bold text-on-surface">{entry.name}</h3>
            <p className="text-xs text-on-surface-variant">{entry.adapter_type.replace('_', ' ')}</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 text-on-surface-variant hover:text-on-surface rounded-md transition-colors"
        >
          <span className="material-symbols-outlined text-xl">close</span>
        </button>
      </div>

      {/* Setup guide */}
      {entry.setup_guide_md && (
        <div className="prose prose-sm max-w-none text-on-surface-variant mb-6 whitespace-pre-line text-sm leading-relaxed">
          {entry.setup_guide_md}
        </div>
      )}

      {/* Credential form */}
      {entry.credentials_schema.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-on-surface mb-3">Credentials</h4>
          {createdId ? (
            <CredentialForm entry={entry} integrationId={createdId} integration={integration} onDone={onClose} />
          ) : (
            <button
              onClick={handleCreate}
              disabled={createIntegration.isPending}
              className="px-4 py-2 bg-primary text-on-primary rounded-md text-sm font-semibold disabled:opacity-40 transition-colors hover:bg-primary/90"
            >
              {createIntegration.isPending ? 'Setting up...' : 'Start setup'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Configured integration card (with health status)
// ---------------------------------------------------------------------------

function ConfiguredCard({
  integration,
  registryEntry,
  health,
}: {
  integration: IntegrationConfigItem
  registryEntry: RegistryEntry | undefined
  health: IntegrationHealthStatus | undefined
}) {
  const deleteIntegration = useDeleteIntegration()
  const githubAppDisconnect = useGithubAppDisconnect()
  const testIntegration = useTestIntegration()
  const { data: credentials } = useCredentials(integration.id)
  const [testing, setTesting] = useState(false)

  const isGithubAppRow = integration.auth_method === 'github_app'

  const handleDisconnect = async () => {
    const label = isGithubAppRow ? 'the GitHub App' : `the ${integration.provider_name} integration`
    const confirmed = window.confirm(
      `Disconnect ${label}? Workspaces that depend on it will stop until you reconnect.` +
        (isGithubAppRow
          ? '\n\nThis only removes the local connection. To revoke OpenSec on GitHub, visit github.com/settings/applications afterwards.'
          : ''),
    )
    if (!confirmed) return
    if (isGithubAppRow) {
      try {
        const r = await githubAppDisconnect.mutateAsync()
        if (typeof window !== 'undefined' && r.manual_revoke_url) {
          // Open the revoke page in a new tab so the user has a one-click
          // path to fully revoke the App on GitHub's side too.
          window.open(r.manual_revoke_url, '_blank', 'noopener,noreferrer')
        }
      } catch {
        // Fall through — local cleanup is best-effort, the integrations
        // list will refresh and reflect any partial state.
      }
    } else {
      deleteIntegration.mutate(integration.id)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      await testIntegration.mutateAsync(integration.id)
    } catch {
      // Health query will refresh and show the error state
    } finally {
      setTesting(false)
    }
  }

  const level = resolveHealthLevel(health)

  return (
    <div className="bg-surface-container-low rounded-lg px-4 py-3 transition-colors">
      <div className="flex items-center gap-4">
        {/* Icon */}
        <div className="w-9 h-9 rounded-lg bg-surface-container-lowest flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-lg text-on-surface-variant">
            {registryEntry?.icon || 'extension'}
          </span>
        </div>

        {/* Name + health status */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-on-surface">
              {integration.provider_name}
            </span>
            {/* Provenance pill: tells the user at a glance whether
                this integration is App-flow or PAT-flow, and (for App
                flow) which GitHub identity it's bound to. */}
            {isGithubAppRow && integration.github_login && (
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                <span className="material-symbols-outlined text-[12px]">verified</span>
                GitHub App · @{integration.github_login}
              </span>
            )}
            {integration.auth_method === 'pat' && (
              <span className="inline-flex items-center rounded-full bg-surface-container-lowest px-2 py-0.5 text-[11px] font-medium text-on-surface-variant">
                Personal access token
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-xs text-on-surface-variant">
              {integration.adapter_type.replace('_', ' ')}
            </span>
            {credentials && credentials.length > 0 && (
              <span className="text-xs text-on-surface-variant">
                {credentials.length} credential{credentials.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          {typeof integration.config?.repo_url === 'string' && integration.config.repo_url && (
            <div className="text-xs text-on-surface-variant mt-0.5 truncate">
              {integration.config.repo_url}
            </div>
          )}
        </div>

        {/* Health indicator */}
        <div className="flex-shrink-0 hidden sm:block">
          <HealthIndicator health={health} />
        </div>

        {/* Test button — min 36px touch target, comfortably above icon-
            only minimum without competing with the disconnect action. */}
        <button
          onClick={handleTest}
          disabled={testing}
          className="inline-flex items-center justify-center min-w-[36px] min-h-[36px] text-on-surface-variant hover:text-primary rounded-md transition-all"
          title="Test connection"
          aria-label="Test connection"
        >
          <span
            className={`material-symbols-outlined text-base ${
              testing ? 'animate-spin' : ''
            }`}
          >
            {testing ? 'progress_activity' : 'sync'}
          </span>
        </button>

        {/* Disconnect button — labelled (not icon-only) since it's
            destructive, with a confirmation dialog and proper App-flow
            cleanup path when the row is github_app-backed. */}
        <button
          onClick={handleDisconnect}
          className="inline-flex items-center gap-1.5 min-h-[36px] rounded-md px-2.5 py-1.5 text-xs font-semibold text-on-surface-variant hover:text-error hover:bg-error/5 transition-colors"
          aria-label="Disconnect integration"
        >
          <span className="material-symbols-outlined text-base">link_off</span>
          Disconnect
        </button>
      </div>

      {/* Mobile health indicator row */}
      <div className="sm:hidden mt-2">
        <HealthIndicator health={health} />
      </div>

      {/* Expanded error detail for error state */}
      {level === 'error' && health?.error_message && (
        <div className="mt-2 rounded-md bg-error-container/15 px-3 py-2 text-xs text-on-error-container">
          {health.error_message}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function IntegrationSettings() {
  const { data: integrations, isLoading: loadingIntegrations } = useIntegrations()
  const { data: registry, isLoading: loadingRegistry } = useRegistry()
  const { data: healthStatuses } = useAllIntegrationsHealth(
    (integrations?.length ?? 0) > 0,
  )
  const [setupEntry, setSetupEntry] = useState<RegistryEntry | null>(null)

  // ADR-0035 / IMPL-0010 — show the App-flow surface only when the
  // backend reports it's available, gated on the env var being set.
  const githubEntry = (registry || []).find((r) => r.id === 'github')
  const githubAppAvailable = githubEntry?.github_app_available === true

  // Use the synchronous auth_method tag the backend stamps on the github
  // integration row instead of racing /status. ``github_app`` = the user
  // already authorized the device flow; ``pat`` = legacy onboarding,
  // suitable to surface the migration banner to.
  const githubIntegration = (integrations || []).find(
    (i) => i.provider_name.toLowerCase() === 'github' && i.enabled,
  )
  const showMigrationBanner =
    githubAppAvailable &&
    githubIntegration !== undefined &&
    githubIntegration.auth_method === 'pat'

  // Page-level resume: if the user just came back from a successful
  // App install on github.com, /setup tagged the URL with
  // ?github_setup=complete. We fire /connect once (idempotent) and
  // mount the modal here so it doesn't depend on the catalog button
  // being rendered (which it isn't, once an integration row exists).
  const { response: resumedFlow, clear: clearResumedFlow } =
    useGithubAppResumeOnReturn()

  // Only enabled integrations count as "configured" — a disabled row
  // (e.g. a github integration created during an in-flight App install
  // before the access token arrives) must NOT unmount the catalog tile's
  // Connect button.
  const configuredIds = new Set(
    (integrations || [])
      .filter((i) => i.enabled)
      .map((i) => i.provider_name.toLowerCase()),
  )

  const getRegistryForIntegration = (integration: IntegrationConfigItem) =>
    registry?.find(
      (r) => r.name.toLowerCase() === integration.provider_name.toLowerCase(),
    )

  const getHealthForIntegration = (integration: IntegrationConfigItem) =>
    healthStatuses?.find((h) => h.integration_id === integration.id)

  const isConfigured = (entry: RegistryEntry) =>
    configuredIds.has(entry.name.toLowerCase())

  const getIntegrationForEntry = (entry: RegistryEntry) =>
    integrations?.find(
      (i) => i.provider_name.toLowerCase() === entry.name.toLowerCase(),
    ) || null

  return (
    <section id="integrations">
      <div className="mb-8">
        <h2 className="text-2xl font-bold tracking-tight text-on-surface mb-2">
          Integrations
        </h2>
        <p className="text-on-surface-variant text-sm max-w-xl">
          Connect vulnerability scanners, ticketing systems, and validation tools to
          power the remediation pipeline.
        </p>
      </div>

      {/* Setup panel */}
      {setupEntry && (
        <SetupPanel
          entry={setupEntry}
          integrationId={getIntegrationForEntry(setupEntry)?.id || null}
          integration={getIntegrationForEntry(setupEntry)}
          onClose={() => setSetupEntry(null)}
        />
      )}

      {resumedFlow && (
        <GithubAppDeviceFlowModal
          connect={resumedFlow}
          onDismiss={clearResumedFlow}
          onTryAgain={clearResumedFlow}
        />
      )}

      {/* Post-connect "what next" callout. Shows when the App-flow row
          is connected but no repo_url has been picked yet — that's the
          state a user lands in if they connected from /settings instead
          of /onboarding/connect. Without this they're left wondering
          "ok, now what?". */}
      {githubIntegration?.auth_method === 'github_app' &&
        !githubIntegration?.config?.repo_url && (
          <div className="rounded-xl bg-tertiary-container/30 px-4 py-3 mb-4 flex items-center justify-between gap-3">
            <div className="min-w-0 flex items-start gap-3">
              <span className="material-symbols-outlined text-tertiary mt-0.5">
                arrow_forward
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-on-surface">
                  You're connected
                  {githubIntegration.github_login
                    ? ` as @${githubIntegration.github_login}`
                    : ''}
                  . Pick a repo to start scanning.
                </p>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  We'll clone it and run the assessment right after.
                </p>
              </div>
            </div>
            <a
              href="/onboarding/connect"
              className="flex-shrink-0 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors"
            >
              Pick a repo
              <span className="material-symbols-outlined text-base">
                arrow_forward
              </span>
            </a>
          </div>
        )}

      {showMigrationBanner && <GithubAppMigrationBanner />}

      {/* Configured integrations */}
      {(integrations || []).length > 0 && (
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm shadow-slate-200/50 mb-6">
          <h3 className="text-sm font-semibold text-on-surface mb-3">
            Connected
          </h3>
          <div className="space-y-2">
            {(integrations || []).map((integration) => (
              <ConfiguredCard
                key={integration.id}
                integration={integration}
                registryEntry={getRegistryForIntegration(integration)}
                health={getHealthForIntegration(integration)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Registry catalog */}
      <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm shadow-slate-200/50">
        <h3 className="text-sm font-semibold text-on-surface mb-4">
          Available integrations
        </h3>
        {loadingRegistry || loadingIntegrations ? (
          <p className="text-sm text-on-surface-variant">Loading catalog...</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(registry || []).map((entry) => {
              const configured = isConfigured(entry)
              return (
                <div
                  key={entry.id}
                  className={`rounded-lg p-4 transition-colors ${
                    entry.status === 'coming_soon'
                      ? 'bg-surface-container-low opacity-60'
                      : 'bg-surface-container-low hover:bg-surface-container'
                  }`}
                >
                  <div className="flex items-start gap-3 mb-2">
                    <div className="w-9 h-9 rounded-lg bg-surface-container-lowest flex items-center justify-center flex-shrink-0">
                      <span className="material-symbols-outlined text-lg text-on-surface-variant">
                        {entry.icon}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-on-surface">
                          {entry.name}
                        </span>
                        <StatusBadge status={entry.status} />
                      </div>
                      <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-2">
                        {entry.description}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-3">
                    <div className="flex gap-1">
                      {entry.capabilities.map((cap) => (
                        <span
                          key={cap}
                          className="text-[10px] text-on-surface-variant bg-surface-container-lowest px-1.5 py-0.5 rounded"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                    {entry.status === 'available' && !configured && (
                      entry.id === 'github' && entry.github_app_available ? (
                        <div className="flex flex-col items-end gap-1.5">
                          <GithubAppConnectButton
                            label="Connect"
                            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-60"
                          />
                          {/* PAT fallback for users who'd rather paste a
                              token (security policy, restricted org App
                              install permissions, etc). text-xs (12px)
                              keeps it secondary without crossing into
                              dark-pattern hidden-link territory. */}
                          <button
                            type="button"
                            onClick={() => setSetupEntry(entry)}
                            className="text-xs text-on-surface-variant hover:text-on-surface underline decoration-dotted underline-offset-2 px-1 py-0.5"
                            data-testid="github-prefer-pat"
                          >
                            Use a token instead
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setSetupEntry(entry)}
                          className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors"
                        >
                          Set up
                        </button>
                      )
                    )}
                    {configured && (
                      <span className="text-xs text-green-600 font-medium flex items-center gap-1">
                        <span className="material-symbols-outlined text-sm">check_circle</span>
                        Connected
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
