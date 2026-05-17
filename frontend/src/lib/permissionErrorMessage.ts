import { parseApiError } from '@/api/client'

/**
 * Map a permission-respond failure to one short, non-destructive sentence
 * the user can act on. Keeps the prompt usable — the buttons stay enabled
 * so a stale 404 or a transient 500 doesn't strand the user.
 */
export function friendlyPermissionError(err: unknown): string {
  if (!err) return "Couldn't reach the backend. Try again."
  const { status, message } = parseApiError(err)
  if (status === 404) {
    return 'This request is no longer pending — the agent may have moved on. Refresh to see the current state.'
  }
  if (status === 401 || status === 403) {
    return 'Not authorised to respond to this request. Sign in and try again.'
  }
  if (status !== null && status >= 500) {
    return "Backend error while responding. Try again — your decision wasn't sent."
  }
  if (
    status === null &&
    (message.toLowerCase().includes('failed to fetch') ||
      message.toLowerCase().includes('networkerror'))
  ) {
    return "Can't reach the backend. Check your connection and try again."
  }
  return "Couldn't reach the backend. Try again."
}
