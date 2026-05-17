import { useState } from 'react'
import {
  useGithubAppConnect,
  useGithubAppDisconnect,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'
import { GithubAppDeviceFlowModal } from './GithubAppDeviceFlowModal'

/**
 * Single-button entry point for the GitHub App + Device Flow onboarding.
 *
 * New-tab UX (B33 / IMPL-0016):
 * 1. Click button → POST /connect → open the GitHub install URL in a
 *    NEW tab via ``window.open``. The original tab stays alive so it
 *    can poll for the install and offer a manual-recovery path if the
 *    callback never reaches this instance (the App's Setup URL is
 *    hardcoded on github.com to ``localhost:8000`` — every Cliff that
 *    isn't bound to that exact port hits the recovery flow).
 * 2. The original tab mounts the GithubAppDeviceFlowModal, which polls
 *    /status. It starts in ``installation_pending`` and flips to
 *    ``device_pending`` once the GET callback lands (or until the user
 *    pastes the installation_id into the ManualRecoveryCard the modal
 *    shows after 30s).
 * 3. Once in ``device_pending`` the user authorizes on the device-code
 *    page, the modal flips to Connected, and dismisses.
 *
 * The button used to do a same-tab ``window.location.href = ...``
 * which made the recovery flow impossible (the original tab navigated
 * away). New-tab is the load-bearing change for B33.
 */
export function GithubAppConnectButton({
  className = '',
  label = 'Connect GitHub',
  returnTo,
}: {
  className?: string
  label?: string
  /**
   * SPA path to land on after the install + authorize round-trip
   * completes. Used by the onboarding flow to keep the user on
   * /onboarding/connect instead of bouncing through Settings.
   * Defaults to /settings (server-side).
   */
  returnTo?: string
}) {
  const connect = useGithubAppConnect()
  const disconnect = useGithubAppDisconnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )

  // Note: detection of ``?github_setup=complete`` (the post-install
  // resume) lives at the page level in IntegrationSettings via
  // useGithubAppResumeOnReturn — the button isn't guaranteed to be
  // mounted at that point (catalog tile unmounts once an integration
  // row exists), so the page is the only safe owner of that effect.

  const handleClick = async () => {
    const r = await connect.mutateAsync({ returnTo })
    if (typeof window !== 'undefined') {
      // Open the install URL in a NEW tab so this tab can keep polling
      // /status. The user's flow: click Install on github.com → if
      // GitHub redirects to a Cliff that doesn't exist on the
      // hard-coded port the user can simply switch back to this tab
      // and use the manual recovery card after 30s.
      window.open(r.install_url, '_blank', 'noopener,noreferrer')
    }
    // Mount the modal IMMEDIATELY (not waiting for the user to come
    // back from GitHub) — that's what enables the 30s timeout that
    // surfaces the manual recovery card on B33-affected deployments.
    setResponse(r)
  }

  const handleTryAgain = async () => {
    await disconnect.mutateAsync().catch(() => undefined)
    setResponse(null)
    await handleClick()
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={connect.isPending}
        className={
          className ||
          'inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-60'
        }
      >
        <span className="material-symbols-outlined text-base">
          rocket_launch
        </span>
        {connect.isPending ? 'Starting...' : label}
      </button>
      {response && (
        <GithubAppDeviceFlowModal
          connect={response}
          onDismiss={() => setResponse(null)}
          onTryAgain={handleTryAgain}
        />
      )}
    </>
  )
}

