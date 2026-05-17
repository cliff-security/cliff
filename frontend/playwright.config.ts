import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * Playwright config for the Session G end-to-end suite.
 *
 * Starts two servers:
 *   - FastAPI backend on :8000, wired with the ``_test_seam.py`` fixture
 *     clone strategy + canned OSV/GitHub responses. The DB is written to
 *     a disposable path so each test run starts with a fresh schema +
 *     zero data.
 *   - Vite dev server on :5173 with ``VITE_USE_REAL_API=1`` so the browser
 *     skips MSW and talks to the real backend.
 *
 * Three browser projects (Chromium, Firefox, WebKit) cover the
 * cross-browser PNG export smoke (``imageExport.ts`` risk row in IMPL-0002).
 *
 * Run:
 *   npx playwright test
 *   npx playwright test --project=chromium
 */

const REPO_ROOT = path.resolve(__dirname, '..')
const FIXTURE_REPO_DIR = path.join(__dirname, 'tests/e2e/fixtures/repo')
const FIXTURE_OSV_DIR = path.join(__dirname, 'tests/e2e/fixtures/osv')
const E2E_DATA_DIR = path.join(REPO_ROOT, 'data', 'e2e')

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false, // backend + DB are single-writer; parallel = races.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://localhost:15173',
    acceptDownloads: true,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: [
    {
      // Clean DB per invocation so the E2E starts from zero. Port 18000 is
      // deliberately offset from the default 8000 so it never collides with
      // a developer's running backend, Docker Desktop, or any other service
      // that happens to be on :8000 on the agent's machine.
      command: `rm -rf "${E2E_DATA_DIR}" && mkdir -p "${E2E_DATA_DIR}" && cd "${REPO_ROOT}/backend" && uv run uvicorn cliff.main:app --host 127.0.0.1 --port 18000`,
      port: 18000,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        CLIFF_DATA_DIR: E2E_DATA_DIR,
        CLIFF_TEST_FIXTURE_REPO_DIR: FIXTURE_REPO_DIR,
        CLIFF_TEST_FIXTURE_OSV_DIR: FIXTURE_OSV_DIR,
        // Inherit PATH so ``uv`` resolves. This mirrors playwright docs.
        PATH: process.env.PATH ?? '',
      },
    },
    {
      command: 'npm run dev -- --port 15173',
      port: 15173,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        VITE_USE_REAL_API: '1',
        VITE_BACKEND_URL: 'http://localhost:18000',
        PATH: process.env.PATH ?? '',
      },
    },
  ],
})
