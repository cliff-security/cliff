/**
 * MSW server for vitest + Node environment. Loads only the findings handlers
 * that remain in the global set; component tests install the session-specific
 * handlers (onboarding, dashboard, posture-fix, completion share-action) via
 * ``sessionHandlers`` + ``server.use(...)`` in ``src/test-setup.ts``.
 */

import { setupServer } from 'msw/node'
import { findingHandlers, handlers } from './handlers'

// Test server gets ``handlers`` (production-side passthrough — empty today)
// plus ``findingHandlers`` (the /api/findings + /api/findings/:id fixtures
// that the dev browser worker no longer registers, per handlers.ts comment).
export const server = setupServer(...handlers, ...findingHandlers)
