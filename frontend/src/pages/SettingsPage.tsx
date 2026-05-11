import ProviderSettings from '@/components/settings/ProviderSettings'
import IntegrationSettings from '@/components/settings/IntegrationSettings'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageShell from '@/components/PageShell'
import {
  AIProviderStatus,
  useOpenAIProvider,
} from '@/components/ai-provider'

export default function SettingsPage() {
  const { open: openAIProvider } = useOpenAIProvider()
  return (
    <ErrorBoundary fallbackTitle="Settings error" fallbackSubtitle="Something went wrong loading settings.">
    <PageShell title="Settings" subtitle="Configure providers, integrations, and preferences.">
      <div className="pb-24">
        <section id="ai-provider" className="mb-12">
          <div className="mb-4">
            <h2 className="text-2xl font-bold tracking-tight text-on-surface mb-2">
              AI provider
            </h2>
            <p className="text-sm text-on-surface-variant">
              The model powering finding enrichment and fix planning.
            </p>
          </div>
          <AIProviderStatus
            onConnect={openAIProvider}
            onSwitchProvider={openAIProvider}
          />
        </section>
        <hr className="border-outline-variant/20 my-12" />
        <ProviderSettings />
        <hr className="border-outline-variant/20 my-12" />
        <IntegrationSettings />
        <hr className="border-outline-variant/20 my-12" />

        {/* About */}
        <section id="about">
          <div className="mb-8">
            <h2 className="text-2xl font-bold tracking-tight text-on-surface mb-2">About</h2>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-8 shadow-sm shadow-outline-variant/10">
            <p className="text-sm text-on-surface-variant leading-relaxed">
              <span className="font-bold text-on-surface">OpenSec</span> is a self-hosted
              cybersecurity remediation copilot. It ingests vulnerability findings, enriches
              them with AI agents, and guides you through planning, ticketing, validating, and
              closing remediations.
            </p>
            <div className="mt-6 flex items-center gap-2 text-xs text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">code</span>
              Single-user community edition &middot; AGPL-3.0 licensed
            </div>
          </div>
        </section>
      </div>
    </PageShell>
    </ErrorBoundary>
  )
}
