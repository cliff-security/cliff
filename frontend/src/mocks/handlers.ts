/**
 * MSW handler exports for the dev browser worker and the vitest server.
 *
 * The browser worker registers ONLY the empty ``handlers`` array — meaning
 * every request flows through to the real FastAPI backend. (Until v0.1.7-alpha
 * we shadowed ``/api/findings`` with the dashboard sample fixture which made
 * the Issues page display stale mock data while the rest of the app rendered
 * live results. That handler is intentionally gone now.)
 *
 * The vitest server (``src/mocks/server.ts``) imports ``findingHandlers``
 * separately and pairs it with ``sessionHandlers`` so component tests keep
 * deterministic responses without leaking back into the dev worker. Tests
 * that need different responses still call ``server.use(...)``.
 */

import { http, HttpResponse } from 'msw'
import { sampleFindings } from './fixtures/dashboard'

/** Handlers registered with the browser MSW worker (production code path). */
export const handlers = []

/** Test-only handlers — imported by ``src/mocks/server.ts`` and registered
 *  with the vitest MSW server. NOT in ``handlers`` so they never reach the
 *  dev browser worker. */
export const findingHandlers = [
  http.get('/api/findings', () => HttpResponse.json(sampleFindings)),
  http.get('/api/findings/:id', ({ params }) => {
    const finding = sampleFindings.find((f) => f.id === params.id)
    if (!finding) {
      return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    }
    return HttpResponse.json(finding)
  }),
]

export {
  setDashboardFixture,
  getActiveDashboardFixture,
  resetStatusPoll,
  type ShareAction,
} from '../test/msw/sessionHandlers'
