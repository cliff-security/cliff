/**
 * From-zero-to-secure end-to-end spec (EXEC-0002 Session G, Milestone I1 + I4).
 *
 * Walks the complete user journey: empty DB → onboarding → assessment →
 * solve one finding → reach completion → download PNG → verify the
 * ``share_actions_used`` row contains ``download``. The same spec runs
 * against Chromium, Firefox, and WebKit projects (see ``playwright.config.ts``)
 * to cover the cross-browser PNG-export risk called out in IMPL-0002.
 *
 * The backend is booted with ``CLIFF_TEST_FIXTURE_REPO_DIR`` +
 * ``CLIFF_TEST_FIXTURE_OSV_DIR`` set, which swaps in a ``clone_strategy``
 * that copies the planted repo under ``tests/e2e/fixtures/repo/`` and a
 * ``MockTransport``-backed httpx client that replays canned OSV responses.
 * No real git, no real network — the spec stays offline.
 */
import { test, expect, APIRequestContext } from '@playwright/test'
import fs from 'node:fs/promises'

const BACKEND = 'http://127.0.0.1:18000'

async function markOneFindingRemediated(request: APIRequestContext): Promise<void> {
  // List current findings and PATCH the first engine-emitted one. Proves the
  // finding-status transition works against the real backend, even though the
  // current UI doesn't expose a one-click "mark remediated" affordance yet.
  const list = await request.get(`${BACKEND}/api/findings`)
  expect(list.ok()).toBeTruthy()
  const findings = (await list.json()) as Array<{
    id: string
    source_type: string
  }>
  const engineFinding = findings.find((f) => f.source_type === 'cliff-assessment')
  expect(engineFinding, 'at least one cliff-assessment finding should exist').toBeTruthy()

  const patch = await request.patch(`${BACKEND}/api/findings/${engineFinding!.id}`, {
    data: { status: 'remediated' },
  })
  expect(patch.ok()).toBeTruthy()
}

async function waitForCompletion(
  request: APIRequestContext,
): Promise<{ completion_id: string; assessment_id: string }> {
  // Poll the dashboard endpoint until a ``completion_id`` is present. The
  // first assessment starts synchronously after ``POST /api/onboarding/repo``;
  // we give it generous headroom to account for slower CI agents.
  const deadline = Date.now() + 45_000
  while (Date.now() < deadline) {
    const resp = await request.get(`${BACKEND}/api/dashboard`)
    if (resp.ok()) {
      const body = (await resp.json()) as {
        completion_id: string | null
        assessment: { id: string; status: string } | null
      }
      if (body.completion_id && body.assessment?.status === 'complete') {
        return {
          completion_id: body.completion_id,
          assessment_id: body.assessment.id,
        }
      }
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('assessment did not reach completion within 45s')
}

test('from zero to secure — onboarding through PNG download', async ({
  page,
  request,
}) => {
  // 1. Welcome → Get started.
  await page.goto('/onboarding/welcome')
  await page.getByRole('button', { name: /get started/i }).click()

  // 2. Connect repo.
  await expect(
    page.getByRole('heading', { name: /connect your project/i }),
  ).toBeVisible()
  await page
    .getByLabel(/repository url/i)
    .fill('https://github.com/cliff/e2e-fixture')
  await page
    .getByLabel(/github personal access token/i)
    .fill('ghp_e2e_test_token_0123456789')
  await page.getByRole('button', { name: /verify and continue/i }).click()

  // 3. Auto-advance waits ~1.2s then navigates to configure AI.
  await expect(
    page.getByRole('heading', { name: /configure your ai model/i }),
  ).toBeVisible({ timeout: 10_000 })
  // Fill a canned API key; the onboarding wizard persists whatever is entered.
  await page.getByLabel(/api key/i).fill('sk-e2e-test-key')
  await page.getByRole('button', { name: /test and continue/i }).click()

  // 4. Ready to assess → Start.
  await expect(
    page.getByRole('heading', { name: /ready to assess/i }),
  ).toBeVisible()
  await page.getByRole('button', { name: /start assessment/i }).click()

  // 5. Lands on dashboard (with ?assessment=running). Wait for the backend
  // to actually finish — poll the completion state, not a UI string, so we
  // don't race the AssessmentProgressList's own polling.
  const { completion_id } = await waitForCompletion(request)

  // 6. "Solve one finding" — API-driven since the current UI doesn't have a
  // one-click remediate button. Proves the status transition works end to
  // end. After the mark the finding shows up as remediated in /api/findings.
  await markOneFindingRemediated(request)

  // 7. Navigate to /dashboard (the wizard sends us with ?assessment=running;
  // we need a clean load so useDashboard refetches).
  await page.goto('/dashboard')
  await expect(
    page.getByRole('heading', { name: /security complete/i }),
  ).toBeVisible({ timeout: 10_000 })
  await expect(page.getByTestId('completion-block')).toBeVisible()

  // 8. Download the summary image via the SummaryActionPanel. The panel
  // lives below the celebration — scroll into view before clicking.
  await page.getByTestId('SummaryActionPanel').scrollIntoViewIfNeeded()
  const downloadPromise = page.waitForEvent('download')
  // ``useShareAction`` fires its POST fire-and-forget in parallel with the
  // PNG export, so we also wait for the response to avoid a race on step 9.
  const shareActionPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes('/api/completion/') &&
      resp.url().endsWith('/share-action') &&
      resp.request().method() === 'POST',
    { timeout: 15_000 },
  )
  await page.getByRole('button', { name: /save \.png/i }).click()
  const download = await downloadPromise
  await shareActionPromise

  const savedPath = await download.path()
  expect(savedPath).toBeTruthy()
  const stats = await fs.stat(savedPath!)
  // ShareableSummaryCard renders 1200×630 @ 2x; a real PNG is well north of
  // 10 KB. A few bytes would mean a blank frame from an export failure.
  expect(stats.size).toBeGreaterThan(10_000)

  // 9. Verify ``share_actions_used`` contains ``download`` on the backend.
  // Poll once more in case the DAO commit lagged the HTTP response.
  let actions: string[] = []
  const verifyDeadline = Date.now() + 5_000
  while (Date.now() < verifyDeadline) {
    const completionResp = await request.get(
      `${BACKEND}/api/completion/${completion_id}`,
    )
    expect(completionResp.ok()).toBeTruthy()
    const body = (await completionResp.json()) as { share_actions_used: string[] }
    actions = body.share_actions_used
    if (actions.includes('download')) break
    await new Promise((r) => setTimeout(r, 200))
  }
  expect(actions).toContain('download')
})
