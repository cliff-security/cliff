/**
 * MSW browser worker — dev-only. Handles the routes in ``./handlers`` that
 * don't yet have a real backend. Everything else flows through the Vite proxy
 * to FastAPI. Set ``VITE_USE_REAL_API=1`` or ``VITE_MSW=off`` to bypass.
 */

import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'
import { permissionDemoHandlers } from './permissionDemo'

// VITE_DEMO_PERMISSION=1 enables a hand-crafted finding + workspace + running
// agent_run that carries a parked ask-tier permission request. Used for
// manual visual verification of the Awaiting-approval chip, the
// "Awaiting approval · N" Review sub-bucket, and the Approve/Deny footer
// prompt without standing up a full backend. Off by default; produces no
// effect in production.
const demoEnabled =
  import.meta.env.VITE_DEMO_PERMISSION === '1' ||
  (typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('demoPermission') === '1')

export const worker = setupWorker(
  ...(demoEnabled ? permissionDemoHandlers : []),
  ...handlers,
)
