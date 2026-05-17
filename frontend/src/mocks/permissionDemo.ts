/**
 * Manual-verification-only MSW handlers for the agent-permission approval
 * gate. Loaded ONLY when ``VITE_DEMO_PERMISSION=1`` is set on the dev
 * server, OR when the page URL carries ``?demoPermission=1``. Returns a
 * single canned finding parked on an ``rm -rf build/`` ask-tier command
 * so a reviewer can eyeball the new chip, the Review sub-bucket, and the
 * footer prompt.
 *
 * Not compiled into production builds because the demo flag is sourced
 * from ``import.meta.env.VITE_DEMO_PERMISSION`` (Vite drops unreferenced
 * env-gated code) and from a URL parameter that the worker doesn't bind
 * unless explicitly opted in.
 */

import { http, HttpResponse } from 'msw'

const FINDING_ID = 'demo-perm-1'
const WORKSPACE_ID = 'ws-demo-1'
const RUN_ID = 'run-demo-1'

const finding = {
  id: FINDING_ID,
  source_type: 'trivy',
  source_id: 'CVE-2026-9999',
  title: 'CVE-2026-9999 — RCE in widget-lib',
  description: null,
  plain_description:
    "Cliff's planner wants to delete the build/ directory before it rebuilds. " +
    'You need to approve before it runs.',
  raw_severity: 'high',
  normalized_priority: 'P1',
  asset_id: null,
  asset_label: 'api-server',
  status: 'in_progress',
  likely_owner: null,
  why_this_matters: null,
  raw_payload: null,
  type: 'vulnerability',
  grade_impact: 'major',
  category: null,
  assessment_id: null,
  pr_url: null,
  created_at: '2026-05-14T00:00:00Z',
  updated_at: '2026-05-14T00:00:00Z',
  derived: {
    section: 'review',
    stage: 'awaiting_permission',
    workspace_id: WORKSPACE_ID,
    pr_url: null,
  },
  exception_reason: null,
  exception_note: null,
}

const runningRun = {
  id: RUN_ID,
  workspace_id: WORKSPACE_ID,
  agent_type: 'remediation_executor',
  status: 'running',
  input_json: null,
  summary_markdown: null,
  confidence: null,
  evidence_json: null,
  structured_output: null,
  next_action_hint: null,
  last_error: null,
  started_at: '2026-05-14T00:00:01Z',
  completed_at: null,
  permission_pending: true,
  permission_request: {
    id: 'perm-demo-1',
    tool: 'bash',
    patterns: ['rm', '-rf', 'build/'],
  },
}

export const permissionDemoHandlers = [
  http.get('/api/findings', () => HttpResponse.json([finding])),
  http.get('/api/findings/:id', () => HttpResponse.json(finding)),
  http.get('/api/integrations', () =>
    HttpResponse.json({ adapters: [] }),
  ),
  http.get('/api/dashboard', () =>
    HttpResponse.json({
      grade: 'C',
      score: 60,
      rationale: '',
      issues_open: 1,
      issues_resolved: 0,
      last_updated: '2026-05-14T00:00:00Z',
    }),
  ),
  http.get('/api/bootstrap', () =>
    HttpResponse.json({
      onboarding_completed: true,
      has_any_assessment: true,
    }),
  ),
  http.get('/api/integrations/ai/status', () =>
    HttpResponse.json({
      state: 'connected',
      provider: 'anthropic',
      source: 'byok',
      connected_at: '2026-05-14T00:00:00Z',
      metadata: null,
      override_model: null,
      model: 'claude-sonnet-4-6',
    }),
  ),
  http.get(`/api/workspaces/${WORKSPACE_ID}/agent-runs`, () =>
    HttpResponse.json([runningRun]),
  ),
  http.get(`/api/workspaces/${WORKSPACE_ID}/sidebar`, () =>
    HttpResponse.json({
      workspace_id: WORKSPACE_ID,
      summary: null,
      evidence: null,
      owner: null,
      plan: {
        steps: [
          { title: 'Bump widget-lib to 2.4.1' },
          { title: 'Clean build/ before rebuild' },
          { title: 'Re-run pytest + npm test' },
        ],
      },
      definition_of_done: null,
      linked_ticket: null,
      validation: null,
      similar_cases: null,
      pull_request: null,
      updated_at: '2026-05-14T00:00:00Z',
    }),
  ),
]
