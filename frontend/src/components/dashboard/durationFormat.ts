/**
 * Shared duration-formatter for IMPL-0009 dashboard surfaces.
 *
 * Under 60s: ``${s.toFixed(1)}s``. 60s and over: ``${m}m ${s}s``.
 * ``null`` / ``undefined`` returns an em-dash so the layout stays stable.
 */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}
