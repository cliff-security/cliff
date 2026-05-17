/**
 * Test-only MSW handlers for routes served by the real backend in production
 * but that component tests still want to stub deterministically. Loaded by
 * vitest only (``src/test-setup.ts`` installs them in ``beforeEach``); never
 * shipped to the dev service worker.
 *
 * Tests can override per-case via ``server.use(...)`` or ``setDashboardFixture``;
 * ``afterEach(() => server.resetHandlers())`` cleans up between tests.
 */
import { http, HttpResponse } from 'msw'
import {
  assessmentStatusSteps,
  getDashboardFixture,
  type DashboardFixtureName,
} from '../../mocks/fixtures/dashboard'

let activeFixture: DashboardFixtureName = 'grade-C-with-issues'

export function setDashboardFixture(name: DashboardFixtureName): void {
  activeFixture = name
}

export function getActiveDashboardFixture(): DashboardFixtureName {
  return activeFixture
}

let statusPollIndex = 0

interface _AIStubState {
  state: 'unconfigured' | 'connected'
  provider: 'openrouter' | 'anthropic' | 'openai' | 'custom' | null
  source: 'autodetect' | 'openrouter-oauth' | 'byok' | null
  connected_at: string | null
  metadata: Record<string, unknown> | null
  model: string | null
}

const _AI_UNCONFIGURED: _AIStubState = {
  state: 'unconfigured',
  provider: null,
  source: null,
  connected_at: null,
  metadata: null,
  model: null,
}

let _aiState: _AIStubState = { ..._AI_UNCONFIGURED }

export function resetAIProviderStub(): void {
  _aiState = { ..._AI_UNCONFIGURED }
}

const _MODEL_FOR_PROVIDER: Record<string, string> = {
  openrouter: 'openrouter/anthropic/claude-sonnet-4.6',
  anthropic: 'anthropic/claude-sonnet-4-6',
  openai: 'openai/gpt-5',
}

export function resetStatusPoll(): void {
  statusPollIndex = 0
}

export type ShareAction = 'download' | 'copy_text' | 'copy_markdown'

export interface StubbedRepoRequest {
  repo_url: string
  github_token: string
}

function deriveRepoName(url: string): string {
  try {
    const u = new URL(url)
    const parts = u.pathname.replace(/^\//, '').replace(/\.git$/, '').split('/')
    return parts.slice(-2).join('/') || url
  } catch {
    return url
  }
}

export const sessionHandlers = [
  // Default the flag ON so gated routes render normally in component tests.
  // FeatureFlagGate tests override this per-case via ``server.use(...)`` to
  // cover the redirect paths.
  http.get('/api/config/bootstrap', () =>
    HttpResponse.json({
      onboarding_completed: true,
      has_any_assessment: true,
    }),
  ),

  // Phase A of the picker — list the repos a token can reach. Tokens with
  // sentinel value ``invalid-token`` simulate the 401 path; everything else
  // returns a couple of fixture repos so the picker has rows to render.
  http.post('/api/onboarding/github/repos', async ({ request }) => {
    const body = (await request.json()) as { github_token?: string }
    if (!body?.github_token) {
      return HttpResponse.json(
        { detail: 'github_token must not be empty', code: 'invalid_token' },
        { status: 422 },
      )
    }
    if (body.github_token === 'invalid-token') {
      return HttpResponse.json(
        {
          detail: 'Token is invalid or lacks read access.',
          code: 'invalid_token',
        },
        { status: 422 },
      )
    }
    return HttpResponse.json({
      repos: [
        {
          full_name: 'alex-dev/fast-markdown',
          html_url: 'https://github.com/alex-dev/fast-markdown',
          private: false,
          default_branch: 'main',
          can_push: true,
        },
        {
          full_name: 'alex-dev/legacy-archive',
          html_url: 'https://github.com/alex-dev/legacy-archive',
          private: true,
          default_branch: 'main',
          can_push: false,
        },
      ],
    })
  }),

  http.post('/api/onboarding/repo', async ({ request }) => {
    const body = (await request.json()) as StubbedRepoRequest

    if (!body?.repo_url || !body?.github_token) {
      return HttpResponse.json(
        { detail: 'repo_url and github_token are required' },
        { status: 422 },
      )
    }

    // Two ways to land on the missing-repo-scope branch in the new flow:
    //   - the token is read-only (sentinel ``no-repo-scope``)
    //   - the user typed a URL via the manual fallback that the token
    //     can't push to (sentinel ``read-only`` in the URL)
    if (
      body.github_token === 'no-repo-scope' ||
      body.repo_url.includes('read-only')
    ) {
      return HttpResponse.json(
        {
          detail:
            'Token has read but not write access. Contents (write) and Pull requests (write) are required.',
          code: 'missing_repo_scope',
        },
        { status: 422 },
      )
    }

    return HttpResponse.json({
      assessment_id: 'asmt_msw_001',
      repo_url: body.repo_url,
      verified: {
        repo_name: deriveRepoName(body.repo_url),
        visibility: 'public',
        default_branch: 'main',
        permissions: ['repo', 'read:user'],
      },
    })
  }),

  http.post('/api/onboarding/complete', async ({ request }) => {
    const body = (await request.json()) as { assessment_id: string }
    if (!body?.assessment_id) {
      return HttpResponse.json(
        { detail: 'assessment_id is required' },
        { status: 422 },
      )
    }
    return HttpResponse.json({ onboarding_completed: true })
  }),

  http.get('/api/dashboard', () =>
    HttpResponse.json(getDashboardFixture(activeFixture)),
  ),

  http.get('/api/assessment/status/:id', () => {
    const step = assessmentStatusSteps[
      Math.min(statusPollIndex, assessmentStatusSteps.length - 1)
    ]
    statusPollIndex += 1
    return HttpResponse.json(step)
  }),

  http.post('/api/posture/fix/:checkName', ({ params }) => {
    const checkName = params.checkName as 'security_md' | 'dependabot_config'
    return HttpResponse.json({
      check_name: checkName,
      workspace_id: `ws_${checkName}_stub`,
    })
  }),

  http.get('/api/settings/providers', () =>
    HttpResponse.json([
      {
        id: 'openai',
        name: 'OpenAI',
        env: ['OPENAI_API_KEY'],
        models: {
          'gpt-4o': { id: 'gpt-4o', name: 'GPT-4o' },
          'gpt-4o-mini': { id: 'gpt-4o-mini', name: 'GPT-4o mini' },
        },
      },
      {
        id: 'anthropic',
        name: 'Anthropic',
        env: ['ANTHROPIC_API_KEY'],
        models: {
          'claude-3-5-sonnet': {
            id: 'claude-3-5-sonnet',
            name: 'Claude 3.5 Sonnet',
          },
        },
      },
      {
        id: 'google',
        name: 'Google',
        env: ['GOOGLE_API_KEY'],
        models: {
          'gemini-1.5-pro': { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro' },
        },
      },
    ]),
  ),

  // ConfigureAI's "Test connection" runs the real provider probe before
  // the wizard advances. Sentinel ``sk-bad-key`` simulates auth failure;
  // any other key resolves to ``ok=true`` so component tests can walk the
  // happy path without standing up OpenCode.
  http.post('/api/settings/providers/test', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      api_key?: string
    }
    if (body?.api_key === 'sk-bad-key') {
      return HttpResponse.json({
        ok: false,
        latency_ms: 142,
        error_code: 'auth_failed',
        error_message: 'The provider rejected the key (401).',
      })
    }
    return HttpResponse.json({
      ok: true,
      latency_ms: 312,
      error_code: null,
      error_message: null,
    })
  }),

  http.put('/api/settings/api-keys/:provider', async ({ params }) =>
    HttpResponse.json({
      provider: String(params.provider),
      key_masked: '****',
      has_credentials: true,
      updated_at: new Date().toISOString(),
    }),
  ),

  http.put('/api/settings/model', async ({ request }) => {
    const body = (await request.json()) as { model_full_id: string }
    const [provider, ...rest] = body.model_full_id.split('/')
    return HttpResponse.json({
      model_full_id: body.model_full_id,
      provider,
      model_id: rest.join('/'),
    })
  }),

  // ---------------------------------------------------------------------
  // AI provider onboarding (ADR-0036 / IMPL-0011)
  //
  // In-memory stub state lives in module scope so /status reflects the
  // most recent /byok call within a single test. ``sk-ant-bad-key``
  // simulates auth_failed; any other key persists and flips state to
  // ``connected``.
  // ---------------------------------------------------------------------

  http.get('/api/integrations/ai/autodetect', () =>
    HttpResponse.json({ found: false, provider: null, source: null }),
  ),

  http.get('/api/integrations/ai/status', () =>
    HttpResponse.json(_aiState),
  ),

  http.post('/api/integrations/ai/byok', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      provider?: string
      api_key?: string
    }
    if ((body.api_key ?? '').includes('bad')) {
      return HttpResponse.json(
        {
          detail: {
            error_code: 'auth_failed',
            error_message: `This key was rejected by ${
              body.provider === 'openai' ? 'OpenAI' : 'Anthropic'
            }.`,
          },
        },
        { status: 400 },
      )
    }
    const provider = (body.provider ?? 'anthropic') as
      | 'openrouter'
      | 'anthropic'
      | 'openai'
      | 'custom'
    _aiState = {
      state: 'connected',
      provider,
      source: 'byok',
      connected_at: new Date().toISOString(),
      metadata: null,
      model: _MODEL_FOR_PROVIDER[provider] ?? null,
    }
    return HttpResponse.json(_aiState)
  }),

  http.post('/api/integrations/ai/disconnect', () => {
    _aiState = { ..._AI_UNCONFIGURED }
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/completion/:id/share-action', async ({ params, request }) => {
    const body = (await request.json()) as { action: ShareAction }
    return HttpResponse.json(
      {
        completion_id: String(params.id),
        share_actions_used: [body.action],
      },
      { status: 200 },
    )
  }),
]
