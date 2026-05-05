/**
 * LastAssessmentPanel — full-width "trust block" on the redesigned dashboard
 * (IMPL-0009 / F7).
 *
 * Four strata: header (verified icon + title + commit/branch + Re-assess),
 * scope strip (folder · files · deps), scanner rows (one per AssessmentTool),
 * footer (sandbox claim + "View raw output" placeholder).
 */
import ScannerRow, { type ScannerRowData } from './ScannerRow'
import { formatDurationMs } from './durationFormat'

export type LastAssessmentInfo = {
  repo_url: string
  finished_at?: string | null
  duration_ms?: number | null
  commit_sha?: string | null
  branch?: string | null
  scanned_files?: number | null
  scanned_deps?: number | null
  scanners?: ScannerRowData[]
}

export default function LastAssessmentPanel({
  data,
  onReassess,
  reassessing,
}: {
  data: LastAssessmentInfo
  onReassess?: () => void
  reassessing?: boolean
}) {
  const repo = humanizeRepo(data.repo_url)
  const finishedAt = humanizeWhen(data.finished_at)
  const duration = data.duration_ms != null ? formatDurationMs(data.duration_ms) : null
  const subtitleParts = [
    finishedAt ? `${finishedAt}` : null,
    duration ? `ran in ${duration}` : null,
    data.commit_sha
      ? `${data.commit_sha} on ${data.branch || 'main'}`
      : null,
  ].filter((p): p is string => Boolean(p))

  return (
    <section
      data-testid="last-assessment-panel"
      className="rounded-2xl border border-outline-variant overflow-hidden"
      style={{ background: 'var(--surface-container-lowest, #ffffff)' }}
    >
      {/* Header */}
      <header
        className="flex items-center justify-between gap-4 px-6 pt-5 pb-4"
        style={{ borderBottom: '1px solid var(--outline-variant, #abb3b7)' }}
      >
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="inline-flex items-center justify-center rounded-xl"
            style={{
              width: 36,
              height: 36,
              background: 'var(--tertiary-container, #d2d9f8)',
              color: 'var(--on-tertiary-container, #444c65)',
            }}
          >
            <span
              className="material-symbols-outlined"
              style={{
                fontSize: 20,
                fontVariationSettings: '"FILL" 1, "wght" 500',
              }}
            >
              verified
            </span>
          </span>
          <div>
            <h2
              className="font-headline font-extrabold leading-tight"
              style={{ fontSize: 17 }}
            >
              Last assessment
            </h2>
            <div
              className="font-mono"
              style={{
                fontSize: 12,
                color: 'var(--on-surface-variant, #586064)',
              }}
            >
              {subtitleParts.join(' · ') || 'No prior assessment'}
            </div>
          </div>
        </div>

        <button
          type="button"
          data-testid="last-assessment-reassess"
          onClick={onReassess}
          disabled={reassessing}
          className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 hover:bg-surface-container disabled:opacity-50"
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--on-surface-variant, #586064)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14 }}
            aria-hidden
          >
            refresh
          </span>
          {reassessing ? 'Re-assessing…' : 'Re-assess'}
        </button>
      </header>

      {/* Scope strip */}
      <div
        className="flex items-center gap-6 px-6 py-3"
        style={{ background: 'var(--surface-container-low, #f1f4f6)' }}
      >
        <ScopeCell
          icon="folder_open"
          label={repo}
          mono
        />
        {data.scanned_files != null && (
          <ScopeCell
            icon="description"
            label={`${data.scanned_files} files`}
            mono
          />
        )}
        {data.scanned_deps != null && (
          <ScopeCell
            icon="package_2"
            label={`${data.scanned_deps} dependencies`}
            mono
          />
        )}
      </div>

      {/* Scanner rows */}
      <ul className="px-6 py-3 list-none">
        {(data.scanners ?? []).map((tool) => (
          <ScannerRow key={tool.id} tool={tool} />
        ))}
        {(data.scanners ?? []).length === 0 && (
          <li
            className="py-3 text-[13px]"
            style={{ color: 'var(--on-surface-variant, #586064)' }}
          >
            No scanner output captured for this assessment.
          </li>
        )}
      </ul>

      {/* Footer */}
      <footer
        className="flex items-center justify-between gap-4 px-6 py-3"
        style={{
          background: 'var(--surface-container-low, #f1f4f6)',
          borderTop: '1px solid var(--outline-variant, #abb3b7)',
        }}
      >
        <div
          className="flex items-center gap-1.5"
          style={{
            fontSize: 11.5,
            color: 'var(--on-surface-variant, #586064)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13 }}
            aria-hidden
          >
            lock
          </span>
          Scanners run in an isolated sandbox · we never store your source
          code.
        </div>
        <button
          type="button"
          title="Raw scanner output viewer ships in a follow-up PR"
          className="inline-flex items-center gap-0.5 cursor-help"
          style={{
            fontSize: 11,
            color: 'var(--primary, #4d44e3)',
            fontWeight: 600,
            background: 'none',
            border: 'none',
            padding: 0,
          }}
        >
          View raw output
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 11 }}
            aria-hidden
          >
            north_east
          </span>
        </button>
      </footer>
    </section>
  )
}

function ScopeCell({
  icon,
  label,
  mono,
}: {
  icon: string
  label: string
  mono?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${mono ? 'font-mono' : ''}`}
      style={{
        fontSize: 12,
        color: 'var(--on-surface, #2b3437)',
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{
          fontSize: 14,
          color: 'var(--on-surface-variant, #586064)',
        }}
        aria-hidden
      >
        {icon}
      </span>
      {label}
    </span>
  )
}

function humanizeRepo(repoUrl: string): string {
  try {
    const u = new URL(repoUrl)
    const path = u.pathname.replace(/^\/+|\.git$|\/+$/g, '')
    return path || repoUrl
  } catch {
    return repoUrl
  }
}

function humanizeWhen(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const seconds = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (seconds < 60) return 'Just now'
  if (seconds < 60 * 60) {
    const m = Math.floor(seconds / 60)
    return `${m} ${m === 1 ? 'minute' : 'minutes'} ago`
  }
  if (seconds < 60 * 60 * 24) {
    const h = Math.floor(seconds / 3600)
    return `${h} ${h === 1 ? 'hour' : 'hours'} ago`
  }
  const days = Math.floor(seconds / 86400)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
}
