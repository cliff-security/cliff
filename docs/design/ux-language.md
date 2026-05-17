# Cliff UX Language Guide

> Living document maintained by the UX team. Defines the vocabulary, tone, patterns, and component catalog for the Cliff product. All new UI work must follow this guide.

**Design system:** The Serene Sentinel (ADR-0011)
**Creative direction:** Editorial Assurance — calm, authoritative, gallery-like
**Last updated:** 2026-04-09

---

## Vocabulary

Use these terms consistently across all UI surfaces. Never mix synonyms.

| Term | Definition | Never say |
|------|-----------|-----------|
| **Finding** | A vulnerability from a scanner | Vulnerability, issue, alert, CVE (CVE is a property of a finding) |
| **Workspace** | A remediation session for one finding | Session, ticket, case, incident |
| **Queue** | The list of findings awaiting remediation | Dashboard, inbox, backlog |
| **Agent** | A specialized AI sub-agent that performs one step | Bot, tool, assistant, model |
| **Agent run** | A single execution of an agent | Task, job, request |
| **Sidebar** | The persistent right panel showing accumulated context | Panel, details, summary |
| **Sidebar state** | The structured data in the sidebar (summary, evidence, owner, plan, ticket, validation) | Context, metadata |
| **Enrich** | Add CVE details, severity, exploit info to a finding | Research, investigate, analyze |
| **Resolve** | Mark a workspace as completed | Close, finish, done |
| **Solve** | Start remediation for a finding (opens a workspace) | Fix, remediate, address |
| **Integration** | A connection to an external tool (scanner, ticketing, etc.) | Plugin, adapter, connector |
| **Severity** | The impact level of a finding (critical, high, medium, low) | Priority, risk (risk is broader) |

## Tone

The user is dealing with security vulnerabilities — a stressful domain. Our UI must **reduce anxiety**, not amplify it.

| Principle | Example | Anti-pattern |
|-----------|---------|-------------|
| **Calm, never alarmist** | "3 critical findings need attention" | "DANGER: 3 CRITICAL VULNERABILITIES DETECTED!" |
| **Authoritative, not commanding** | "The enricher found exploit code available" | "You must patch this immediately" |
| **Supportive, not condescending** | "Enrich this finding to understand the impact" | "Click here to learn about this vulnerability" |
| **Concise, not terse** | "No findings match your filters" | "Empty" or "Nothing found" |
| **Action-oriented** | "Solve" / "Enrich finding" / "Build plan" | "Submit" / "Process" / "Execute" |

## Severity presentation

Severity is shown consistently across all surfaces using the same tokens:

| Level | Text color | Background | Badge style |
|-------|-----------|------------|------------|
| Critical | `text-error` | `bg-error-container/30` | Filled, rounded-full |
| High | `text-error` | `bg-error-container/30` | Same as critical (distinguished by label) |
| Medium | `text-tertiary` | `bg-tertiary-container/30` | Filled, rounded-full |
| Low | `text-on-surface-variant` | `bg-surface-container-high` | Filled, rounded-full |

Always show both the badge color AND the text label. Never rely on color alone.

## Progress and status patterns

| State | Visual pattern | Token |
|-------|---------------|-------|
| Loading | Spinning circle (border animation) | `border-primary/30 border-t-primary` |
| Agent running | Pulsing dot + "Thinking..." with bouncing dots | `bg-primary/40 animate-pulse` |
| Streaming | Text appearing with cursor indicator | Inline cursor block |
| Success | Check icon + green text | Use `text-tertiary` (NOT arbitrary `green-*`) |
| Error | Error icon + error text | `text-error`, `bg-error-container/20` |
| Empty | Centered icon + title + subtitle + optional CTA | `EmptyState` component |

## Agent activity pattern

When an agent runs, the user sees this sequence:
1. **Triggered:** Action chip becomes disabled, chat shows "thinking" indicator
2. **Running:** Bouncing dots animation, streaming text appears
3. **Complete:** Structured result appears in chat + sidebar updates simultaneously
4. **Error:** Error message in chat with error styling

## Layout patterns

| Pattern | Structure |
|---------|-----------|
| **List page** (Queue, History) | `PageShell` + filters + list of cards |
| **Detail page** (Workspace) | Header bar + center content + right sidebar |
| **Settings page** | `PageShell` + sections separated by tonal shifts |
| **Empty state** | `EmptyState` component with icon, message, CTA |

## Spacing and rhythm

- Page padding: `px-8 py-6` (content area)
- Card gap: `space-y-3` for lists
- Section gap: `space-y-6` for page sections
- Sidebar width: Fixed right panel
- Nav width: `w-20` fixed left

## Interactive states

Every interactive element must have:
- **Default:** Resting state
- **Hover:** Subtle background shift or shadow
- **Active/Pressed:** `active:scale-95` for buttons
- **Disabled:** `opacity-50` + `cursor-not-allowed`
- **Focus-visible:** Ring for keyboard navigation (currently a gap — see audit)

---

## Component Catalog

| Component | Location | Purpose | Compliance |
|-----------|----------|---------|------------|
| `PageShell` | `components/PageShell.tsx` | Page header with title, subtitle, actions | Pass |
| `FindingRow` | `components/FindingRow.tsx` | Queue list item with severity, metadata | Pass |
| `SeverityBadge` | `components/SeverityBadge.tsx` | Color-coded severity indicator | Pass |
| `ActionChips` | `components/ActionChips.tsx` | 5 quick-action buttons for agents | Border violation |
| `ActionButton` | `components/ActionButton.tsx` | Primary/outline CTA button | Border violation (outline variant) |
| `AgentRunCard` | `components/AgentRunCard.tsx` | Agent execution status display | Border + arbitrary color violations |
| `ResultCard` | `components/ResultCard.tsx` | Agent output with accept/dismiss | Border violations |
| `WorkspaceSidebar` | `components/WorkspaceSidebar.tsx` | Right sidebar with 7 context sections | Border violations |
| `EmptyState` | `components/EmptyState.tsx` | Empty page placeholder with CTA | Pass |
| `ListCard` | `components/ListCard.tsx` | Hoverable card wrapper | Minor border violation |
| `HistoryCard` | `components/HistoryCard.tsx` | Completed workspace card | Border + arbitrary color violations |
| `HistoryDetail` | `components/HistoryDetail.tsx` | Tabbed detail view (chat, runs, context) | Border violations |
| `Markdown` | `components/Markdown.tsx` | Markdown renderer with syntax highlighting | Pass |
| `SideNav` | `components/layout/SideNav.tsx` | Fixed left navigation | Border violations (active indicator) |
| `TopBar` | `components/layout/TopBar.tsx` | Sticky header with nav + search | Border + arbitrary green |
| `ProviderSettings` | `components/settings/ProviderSettings.tsx` | AI provider/model config | Arbitrary green colors |
| `IntegrationSettings` | `components/settings/IntegrationSettings.tsx` | Integration setup + health | Arbitrary green/red colors |

**Pass:** 4 components | **Violations:** 13 components

---

_This guide is the source of truth for UX decisions. Update it as components are fixed or new patterns are established._
