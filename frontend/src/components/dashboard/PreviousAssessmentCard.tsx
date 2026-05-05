/**
 * PreviousAssessmentCard — continuity card under the live assessment surface
 * (IMPL-0009 / F9). Renders only when the status response carries a
 * ``previous_assessment`` block (single prior completed scan).
 */

export type PreviousAssessmentInfo = {
  assessment_id: string
  grade?: string | null
  open_count?: number
  commit_sha?: string | null
  finished_at?: string | null
  report_href?: string
}

export default function PreviousAssessmentCard({
  info,
  onViewLastReport,
}: {
  info: PreviousAssessmentInfo
  onViewLastReport?: () => void
}) {
  const grade = info.grade ?? '—'
  const openCount = info.open_count ?? 0
  const commit = info.commit_sha
  const finishedAt = humanizeWhen(info.finished_at)

  const bodyParts = [
    `Grade ${grade}`,
    `${openCount} open ${openCount === 1 ? 'finding' : 'findings'}`,
    commit ? null : null,
    finishedAt,
  ].filter((p): p is string => Boolean(p))

  return (
    <section
      data-testid="previous-assessment-card"
      className="rounded-2xl border border-outline-variant flex items-center gap-4 px-5 py-4 mt-4"
      style={{ background: 'var(--surface-container-low, #f1f4f6)' }}
    >
      <span
        aria-hidden
        className="material-symbols-outlined"
        style={{
          fontSize: 20,
          color: 'var(--on-surface-variant, #586064)',
        }}
      >
        history
      </span>
      <div className="flex-1 min-w-0">
        <div
          className="text-[10.5px] font-bold uppercase tracking-wider"
          style={{ color: 'var(--on-surface-variant, #586064)' }}
        >
          Previous assessment
        </div>
        <div
          className="mt-0.5 truncate"
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--on-surface, #2b3437)',
          }}
        >
          {bodyParts.join(' · ')}
          {commit && (
            <>
              {' '}·{' '}
              <span className="font-mono">{commit}</span>
            </>
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={onViewLastReport}
        className="inline-flex items-center gap-1 hover:underline"
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--primary, #4d44e3)',
          background: 'none',
          border: 'none',
          padding: 0,
        }}
      >
        View last report
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 13 }}
          aria-hidden
        >
          arrow_forward
        </span>
      </button>
    </section>
  )
}

function humanizeWhen(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const seconds = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (seconds < 60) return 'Just now'
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60)
    return `${m} ${m === 1 ? 'minute' : 'minutes'} ago`
  }
  if (seconds < 86_400) {
    const h = Math.floor(seconds / 3600)
    return `${h} ${h === 1 ? 'hour' : 'hours'} ago`
  }
  const d = Math.floor(seconds / 86_400)
  return `${d} ${d === 1 ? 'day' : 'days'} ago`
}
