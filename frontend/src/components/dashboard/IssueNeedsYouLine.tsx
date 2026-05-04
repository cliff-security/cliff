/**
 * IssueNeedsYouLine — single-line callout under the grade hero.
 *
 * Composes a sentence around the live ``needs_you`` counts from the
 * dashboard payload. When all three are zero, renders a calm
 * "You're caught up" variant instead. Right-aligned link points into
 * the Issues page (Review section by default).
 */
const NUMBER_WORDS: Record<number, string> = {
  0: 'no',
  1: 'one',
  2: 'two',
  3: 'three',
  4: 'four',
  5: 'five',
  6: 'six',
  7: 'seven',
  8: 'eight',
  9: 'nine',
}

function spell(n: number): string {
  return NUMBER_WORDS[n] ?? String(n)
}

function plural(noun: string, n: number): string {
  return n === 1 ? noun : `${noun}s`
}

function buildCopy(plansWaiting: number, prsReady: number): string {
  const parts: string[] = []
  if (plansWaiting > 0) {
    parts.push(`${spell(plansWaiting)} ${plural('plan', plansWaiting)}`)
  }
  if (prsReady > 0) {
    parts.push(`${spell(prsReady)} ${plural('PR', prsReady)}`)
  }
  if (parts.length === 0) return ''
  const verb = plansWaiting + prsReady === 1 ? 'is' : 'are'
  return `${parts.join(' and ')} ${verb} waiting on you.`
}

export default function IssueNeedsYouLine({
  plansWaiting,
  prsReady,
  criticalTodo,
  onOpenReview,
}: {
  plansWaiting: number
  prsReady: number
  criticalTodo: number
  onOpenReview?: () => void
}) {
  const reviewMsg = buildCopy(plansWaiting, prsReady)
  const total = plansWaiting + prsReady + criticalTodo

  if (total === 0) {
    return (
      <div
        data-testid="issue-needs-you-line"
        data-state="caught-up"
        className="rounded-2xl px-5 py-3.5 flex items-center gap-3"
        style={{
          background: 'var(--surface-container-low, #f1f4f6)',
          border: '1px solid var(--outline-variant, #abb3b7)',
        }}
      >
        <span
          className="material-symbols-outlined text-tertiary"
          style={{ fontSize: 18 }}
          aria-hidden
        >
          check_circle
        </span>
        <span className="text-[13px] text-on-surface font-medium">
          You're caught up. Run an assessment when you're ready.
        </span>
      </div>
    )
  }

  // Compose the message: prefer review counts, append a critical-todo nudge
  // when applicable.
  const message = reviewMsg
    || (criticalTodo > 0
      ? `${spell(criticalTodo)} critical ${plural('issue', criticalTodo)} ${
          criticalTodo === 1 ? 'is' : 'are'
        } sitting in Todo.`
      : '')

  return (
    <div
      data-testid="issue-needs-you-line"
      data-state="needs-you"
      className="rounded-2xl px-5 py-3.5 flex items-center gap-3"
      style={{
        background: 'var(--surface-container-low, #f1f4f6)',
        border: '1px solid var(--outline-variant, #abb3b7)',
      }}
    >
      <span
        className="material-symbols-outlined text-primary"
        style={{ fontSize: 18 }}
        aria-hidden
      >
        rate_review
      </span>
      <span className="text-[13px] text-on-surface font-medium">{message}</span>
      {criticalTodo > 0 && reviewMsg && (
        <span className="text-[12.5px] text-on-surface-variant ml-1">
          {spell(criticalTodo)} critical {plural('issue', criticalTodo)} in
          Todo.
        </span>
      )}
      <button
        type="button"
        onClick={onOpenReview}
        className="text-[12.5px] text-primary font-semibold ml-auto inline-flex items-center gap-1 hover:underline"
      >
        Open Review
        <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
          arrow_forward
        </span>
      </button>
    </div>
  )
}
