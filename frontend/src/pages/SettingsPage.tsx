/**
 * SettingsPage — Cliff Cyberdeck operator console.
 *
 * Uses the shared ``PageShell`` topbar so the title strip matches
 * Dashboard / Issues / History / etc. Below the topbar: a 220px left
 * tab rail in `--cd-bg-1` + the active section on the right. Section
 * H2s use Manrope 22px / fg-1 / -0.02em per `ui-kit/settings.jsx`.
 *
 * Tab set is the actual OpenSec settings surface — AI provider,
 * Integrations, About — not the ui-kit's hypothetical Scope/Agents/etc.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import IntegrationSettings from '@/components/settings/IntegrationSettings'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageShell from '@/components/PageShell'
import {
  AIProviderStatus,
  useOpenAIProvider,
} from '@/components/ai-provider'

type TabId = 'ai' | 'integrations' | 'about'

interface TabDef {
  id: TabId
  label: string
  hash: string
}

const TABS: TabDef[] = [
  { id: 'ai', label: 'AI provider', hash: '#ai-provider' },
  { id: 'integrations', label: 'Integrations', hash: '#integrations' },
  { id: 'about', label: 'About', hash: '#about' },
]

function SettingsTab({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  // Sentence-case Inter rails per the readability brief (D + E2). The
  // active tab gets a weight bump + sage left rule, no text glow — same
  // pattern as `.cd-nav` rows in the global side-nav.
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        width: '100%',
        padding: '10px 16px',
        fontFamily: 'var(--cd-sans)',
        fontSize: 14,
        fontWeight: active ? 600 : 500,
        letterSpacing: 0,
        textTransform: 'none',
        background: 'transparent',
        color: active ? 'var(--cd-green)' : 'var(--cd-fg-2)',
        borderLeft: `2px solid ${active ? 'var(--cd-green)' : 'transparent'}`,
        borderTop: 'none',
        borderRight: 'none',
        borderBottom: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'all 120ms',
        lineHeight: 1.2,
      }}
    >
      {label}
    </button>
  )
}

function SectionHeading({
  title,
  description,
}: {
  title: string
  description?: string
}) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h2
        className="font-display font-bold"
        style={{
          fontSize: 22,
          color: 'var(--cd-fg-1)',
          letterSpacing: '-0.02em',
          margin: 0,
        }}
      >
        {title}
      </h2>
      {description && (
        <p
          style={{
            fontSize: 13,
            color: 'var(--cd-fg-3)',
            marginTop: 6,
            maxWidth: 560,
            lineHeight: 1.5,
          }}
        >
          {description}
        </p>
      )}
    </div>
  )
}

function tabIdForHash(hash: string): TabId {
  const match = TABS.find((t) => t.hash === hash)
  return match?.id ?? 'ai'
}

export default function SettingsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [tab, setTab] = useState<TabId>(() => tabIdForHash(location.hash))
  const { open: openAIProvider } = useOpenAIProvider()

  useEffect(() => {
    setTab(tabIdForHash(location.hash))
  }, [location.hash])

  const selectTab = (id: TabId) => {
    setTab(id)
    const def = TABS.find((t) => t.id === id)
    if (def) navigate({ hash: def.hash }, { replace: true })
  }

  return (
    <ErrorBoundary
      fallbackTitle="Settings error"
      fallbackSubtitle="Something went wrong loading settings."
    >
      <PageShell
        title="Settings"
        subtitle="How cliff works in your repo."
      >
        <div style={{ display: 'flex', minHeight: 'calc(100vh - 80px)' }}>
          <aside
            aria-label="Settings tabs"
            style={{
              width: 220,
              flexShrink: 0,
              background: 'var(--cd-bg-1)',
              borderRight: '1px solid var(--cd-rule)',
              padding: '14px 0',
            }}
          >
            {TABS.map((t) => (
              <SettingsTab
                key={t.id}
                label={t.label}
                active={tab === t.id}
                onClick={() => selectTab(t.id)}
              />
            ))}
          </aside>

          <div
            className="cd-scroll"
            style={{
              flex: 1,
              minWidth: 0,
              padding: '32px 36px 80px',
              maxWidth: 920,
            }}
          >
            {tab === 'ai' && (
              <section id="ai-provider">
                <SectionHeading
                  title="AI provider"
                  description="The model powering finding enrichment and fix planning."
                />
                <AIProviderStatus
                  onConnect={openAIProvider}
                  onSwitchProvider={openAIProvider}
                />
              </section>
            )}

            {tab === 'integrations' && (
              /* IntegrationSettings owns its own h2 + description. */
              <IntegrationSettings />
            )}

            {tab === 'about' && (
              <section id="about">
                <SectionHeading title="About" />
                <div
                  className="cd-card"
                  style={{ padding: '22px 24px' }}
                >
                  <p
                    style={{
                      fontSize: 13.5,
                      color: 'var(--cd-fg-2)',
                      lineHeight: 1.6,
                    }}
                  >
                    <strong style={{ color: 'var(--cd-fg-1)' }}>cliff</strong>{' '}
                    is a self-hosted cybersecurity remediation copilot. It
                    ingests vulnerability findings, enriches them with AI
                    agents, and guides you through planning, ticketing,
                    validating, and closing remediations.
                  </p>
                  <div
                    style={{
                      marginTop: 18,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontFamily: 'var(--cd-mono)',
                      fontSize: 11,
                      color: 'var(--cd-fg-4)',
                      letterSpacing: '0.08em',
                    }}
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: 14 }}
                      aria-hidden
                    >
                      code
                    </span>
                    Single-user community edition · AGPL-3.0 licensed
                  </div>
                </div>
              </section>
            )}
          </div>
        </div>
      </PageShell>
    </ErrorBoundary>
  )
}
