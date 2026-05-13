/**
 * PageSpinner — Cliff Cyberdeck in-flight indicator for full-page loads.
 *
 * Uses the trademark sage pulse-dot (`.cd-loader`) instead of a circular
 * spinner. One dot, one cadence, one colour — per the system rule.
 * Copy follows the voice playbook (G3 of the readability brief): Cliff
 * narrates what he's doing rather than yelling "LOADING".
 */
export default function PageSpinner() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading"
      className="flex flex-col items-center gap-3 py-24"
    >
      <span className="cd-loader cd-loader--lg" aria-hidden />
      <span style={{ fontSize: 13, color: 'var(--cd-fg-4)' }}>
        Cliff is loading the page…
      </span>
    </div>
  )
}
