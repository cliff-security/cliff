import { useState } from 'react'
import { parseApiError } from '@/api/client'
import { useGithubAppManualSetup } from '@/api/githubApp'

/**
 * Manual recovery affordance for B33 — shown after a 30-second polling
 * timeout when the post-install GET callback never reached this Cliff
 * instance.
 *
 * The shared GitHub App's Setup URL is registered globally on
 * github.com to ``http://localhost:8000/api/integrations/github/setup``.
 * Any Cliff deployment NOT on host port 8000 (Docker remap, parallel
 * dev stack, reverse proxy) misses the callback. The user finds their
 * ``installation_id`` in one of two places:
 *
 *   1. The redirect URL GitHub took them to (the param is right there
 *      in the address bar of whatever wrong-port URL they ended up on).
 *   2. The App's installation page on github.com — the integer at the
 *      end of e.g. ``/installations/12345``.
 *
 * The submitted ``installation_id`` + ``csrf_state`` POST through
 * ``/api/integrations/github/setup/manual``, which runs the same CSRF
 * validation as the GET callback. That validation is load-bearing: it's
 * what stops an attacker who tricks the user into pasting a
 * hostile ``installation_id`` from binding it.
 */
export function ManualRecoveryCard({
  csrfState,
}: {
  /** CSRF state issued by the most recent POST /connect. The backend
   * refuses any installation_id that wasn't bound to a state it
   * issued, so an empty/mismatched value will 400. */
  csrfState: string
}) {
  const manualSetup = useGithubAppManualSetup()
  const [installationId, setInstallationId] = useState('')
  const [submissionError, setSubmissionError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmissionError(null)
    const trimmed = installationId.trim()
    const parsed = Number(trimmed)
    // Defend the network call: GitHub installation IDs are positive
    // integers. If we let a NaN through, the backend's gt=0 validator
    // rejects it with a generic 422 that's harder to explain.
    if (!trimmed || !Number.isInteger(parsed) || parsed <= 0) {
      setSubmissionError(
        'Installation ID must be a positive integer (e.g. 12345).',
      )
      return
    }
    try {
      // The mutation pushes the resulting /status into the query cache
      // on success, which causes the modal's ``installAttached`` to flip
      // true and unmount this card. No imperative callback needed.
      await manualSetup.mutateAsync({
        installation_id: parsed,
        state: csrfState,
      })
    } catch (err) {
      // parseApiError unwraps the ``NNN: body`` shape that ``request``
      // throws and pulls FastAPI's ``detail`` field out of the JSON body
      // — that's the human-readable string the backend wrote (e.g. the
      // CSRF mismatch message). The recourse for any failure here is to
      // start the connect flow over from the catalog tile.
      const { message } = parseApiError(err)
      setSubmissionError(message || 'Could not register installation.')
    }
  }

  return (
    <div
      role="region"
      aria-label="Manual GitHub install recovery"
      data-testid="github-manual-recovery"
      className="rounded-xl bg-surface-container-low p-5 mt-4"
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-surface-container-lowest flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-primary">
            help_outline
          </span>
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-on-surface">
            Couldn&apos;t detect your install
          </p>
          <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">
            GitHub may have redirected you to <span className="font-mono">localhost:8000</span>
            {' '}instead of this Cliff. Open the App&apos;s installation page on GitHub,
            copy the installation ID from the URL (e.g.{' '}
            <span className="font-mono">/installations/12345</span>), and paste it here.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="mt-4">
        {/* The CSRF state is a hidden field so the form has a complete,
            inspectable payload. Submission MUST include it — the backend
            rejects any installation_id that wasn't bound to a state we
            issued. */}
        <input
          type="hidden"
          name="state"
          data-testid="github-manual-recovery-state"
          value={csrfState}
          readOnly
        />
        <label
          htmlFor="github-manual-recovery-installation-id"
          className="block text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-2"
        >
          Installation ID
        </label>
        <div className="flex gap-2">
          <input
            id="github-manual-recovery-installation-id"
            name="installation_id"
            type="text"
            inputMode="numeric"
            pattern="[0-9]+"
            placeholder="12345"
            value={installationId}
            onChange={(e) => setInstallationId(e.target.value)}
            className="flex-1 rounded-md bg-surface-container-lowest px-3 py-2 text-sm font-mono text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-2 focus:ring-primary/40 min-h-[40px]"
            disabled={manualSetup.isPending}
            data-testid="github-manual-recovery-input"
            aria-describedby={
              submissionError
                ? 'github-manual-recovery-error'
                : undefined
            }
          />
          <button
            type="submit"
            disabled={manualSetup.isPending || installationId.trim() === ''}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-60 min-h-[40px]"
            data-testid="github-manual-recovery-submit"
          >
            {manualSetup.isPending ? 'Connecting…' : 'Connect'}
          </button>
        </div>
        {submissionError && (
          <p
            id="github-manual-recovery-error"
            role="alert"
            className="mt-2 text-xs text-error"
            data-testid="github-manual-recovery-error"
          >
            {submissionError}
          </p>
        )}
      </form>
    </div>
  )
}
