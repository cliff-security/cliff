/**
 * Q01R B24 — turn an ``onAutoFix`` rejection into something human-readable.
 *
 * The shared ``request`` helper throws ``Error("<status>: <raw body>")``; for
 * FastAPI 422s the body is a JSON object shaped like
 * ``{"detail":[{"type":"...","loc":["path","check_name"],"msg":"...","input":"..."}]}``.
 * We pull the first ``detail[*].msg`` so the user sees the actual reason
 * (e.g. "Input should be 'security_md' or 'dependabot_config'") instead of
 * the raw JSON blob.
 *
 * Lives in its own module (not co-located with ``GateRow``) so the
 * ``react-refresh/only-export-components`` ESLint rule stays happy.
 */
export function formatAutoFixError(err: unknown): string {
  const fallback = "Auto-fix failed. Try again, or open the posture check to fix it manually."
  if (!err) return fallback
  const message = err instanceof Error ? err.message : String(err)
  // ``request`` throws ``${status}: ${body}``; try to extract the body.
  const colonIdx = message.indexOf(':')
  const body = colonIdx >= 0 ? message.slice(colonIdx + 1).trim() : message.trim()
  // Try JSON first; if that fails, fall back to the raw message.
  try {
    const parsed = JSON.parse(body) as unknown
    if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
      const detail = (parsed as { detail: unknown }).detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0]
        if (first && typeof first === 'object' && 'msg' in first) {
          const msg = (first as { msg: unknown }).msg
          if (typeof msg === 'string' && msg.length > 0) return msg
        }
      }
      if (typeof detail === 'string' && detail.length > 0) return detail
    }
  } catch {
    // Not JSON — fall through to the trimmed message.
  }
  return message || fallback
}
