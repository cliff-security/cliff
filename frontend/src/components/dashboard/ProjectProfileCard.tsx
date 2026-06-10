/**
 * ProjectProfileCard — the dashboard surface for the per-repo Project profile
 * (ADR-0053 / PRD-0009 Story 1 + 4).
 *
 * Shows that Cliff has gotten to know the project, how fresh that understanding
 * is, and a re-profile action. Cyberdeck-calm, additive — renders nothing when
 * there's no repo and no profile. (UX-0009 owns the eventual polish.)
 */

import { useRebuildProfile, useRepoProfile } from '@/api/repos'
import type { RepoProfileStatusValue } from '@/api/repos'

const STATUS_LABEL: Record<RepoProfileStatusValue, string> = {
  none: 'Not profiled',
  building: 'Getting to know it…',
  ready: 'Profiled',
  stale: 'Out of date',
  error: "Couldn't profile",
}

const STATUS_TONE: Record<RepoProfileStatusValue, string> = {
  none: 'var(--cd-fg-4)',
  building: 'var(--cd-green)',
  ready: 'var(--cd-green)',
  stale: 'var(--cd-amber, #E2B441)',
  error: 'var(--cd-red, #E97A8E)',
}

function timeAgo(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 60) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

function summaryFrom(md: string | null): string | null {
  if (!md) return null
  const summary = md.match(/\*\*summary:\*\*\s*(.+)/i)
  if (summary) return summary[1].trim()
  const kind = md.match(/\*\*kind:\*\*\s*(.+)/i)
  if (kind) return `A ${kind[1].trim().replace(/_/g, ' ')} project.`
  return null
}

export default function ProjectProfileCard() {
  const { data } = useRepoProfile()
  const rebuild = useRebuildProfile()

  if (!data || (data.status === 'none' && !data.repo_url)) return null

  const { status } = data
  const summary = summaryFrom(data.profile_md)
  const when = timeAgo(data.profiled_at)
  const sha = data.last_profiled_sha?.slice(0, 7)
  const busy = status === 'building' || rebuild.isPending

  const headline =
    status === 'building'
      ? 'Getting to know your project…'
      : status === 'none'
        ? 'Cliff hasn’t profiled this project yet.'
        : (summary ?? 'Cliff has a profile of this project.')

  return (
    <section
      data-testid="project-profile-card"
      className="rounded-[6px] p-5"
      style={{
        background: 'var(--cd-card)',
        boxShadow: 'inset 0 0 0 1px var(--cd-rule)',
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span
          className="font-mono uppercase text-[11px]"
          style={{ letterSpacing: '0.22em', color: 'var(--cd-fg-4)' }}
        >
          Project profile
        </span>
        <span
          className="font-mono text-[11px]"
          style={{ letterSpacing: '0.06em', color: STATUS_TONE[status] }}
        >
          {STATUS_LABEL[status]}
        </span>
      </div>

      <p className="mt-2 text-[13px] leading-snug" style={{ color: 'var(--cd-fg-2)' }}>
        {headline}
      </p>

      {when && status !== 'none' ? (
        <p className="mt-1 text-[12px]" style={{ color: 'var(--cd-fg-3)' }}>
          Built {when}
          {sha ? ` · ${sha}` : ''}
        </p>
      ) : null}

      <div className="mt-3 flex items-center gap-4">
        <button
          type="button"
          disabled={busy}
          onClick={() => rebuild.mutate(undefined)}
          className="text-[12.5px] font-medium"
          style={{
            color: busy ? 'var(--cd-fg-4)' : 'var(--cd-green)',
            cursor: busy ? 'default' : 'pointer',
          }}
        >
          {status === 'none' ? 'Profile now' : 'Re-profile'}
        </button>
        {rebuild.data?.status === 'skipped' ? (
          <span className="text-[12px]" style={{ color: 'var(--cd-fg-4)' }}>
            Connect an AI provider first.
          </span>
        ) : null}
      </div>

      {data.profile_md && status !== 'none' ? (
        <details className="mt-3">
          <summary
            className="text-[12px] cursor-pointer"
            style={{ color: 'var(--cd-fg-3)' }}
          >
            What Cliff understood
          </summary>
          <pre
            className="mt-2 text-[11.5px] whitespace-pre-wrap"
            style={{ color: 'var(--cd-fg-3)', fontFamily: 'inherit' }}
          >
            {data.profile_md}
          </pre>
        </details>
      ) : null}
    </section>
  )
}
