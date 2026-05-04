/**
 * Component-level happy path + error path for the onboarding wizard.
 * Exercises all four pages (1.0 → 1.1 → 1.4 → 1.5) against the MSW
 * handlers defined in `src/test/msw/sessionHandlers.ts`.
 *
 * As of the repo-picker change, frame 1.1 is two-phase:
 *   A) paste PAT → POST /api/onboarding/github/repos
 *   B) pick from the list → POST /api/onboarding/repo
 * The test handlers return two fixture repos for any non-sentinel token.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Welcome from '@/pages/onboarding/Welcome'
import ConnectRepo from '@/pages/onboarding/ConnectRepo'
import ConfigureAI from '@/pages/onboarding/ConfigureAI'
import StartAssessment from '@/pages/onboarding/StartAssessment'

function renderWizard(initialPath = '/onboarding/welcome') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/onboarding/welcome', element: <Welcome /> },
      { path: '/onboarding/connect', element: <ConnectRepo /> },
      { path: '/onboarding/ai', element: <ConfigureAI /> },
      { path: '/onboarding/start', element: <StartAssessment /> },
      {
        path: '/dashboard',
        element: <div data-testid="dashboard-landed">dashboard</div>,
      },
    ],
    { initialEntries: [initialPath] },
  )
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('onboarding wizard', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('walks the happy path: welcome → connect (token + pick) → ai → start → dashboard', async () => {
    const user = userEvent.setup()
    renderWizard()

    // 1.0 Welcome
    expect(
      screen.getByRole('heading', { name: /welcome to opensec/i }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /get started/i }))

    // 1.1 Connect repo — phase A: paste PAT, click Continue.
    expect(
      await screen.findByRole('heading', { name: /connect your project/i }),
    ).toBeInTheDocument()
    await user.type(
      screen.getByLabelText(/github personal access token/i),
      'ghp_validtoken',
    )
    await user.click(screen.getByRole('button', { name: /^continue$/i }))

    // 1.1 phase B: pick the writable repo from the picker.
    // The clickable element inside the listbox is the <button> nested in the
    // <li role="option">, not the option itself.
    const pickerRow = await screen.findByRole('button', {
      name: /alex-dev\/fast-markdown/i,
    })
    await user.click(pickerRow)

    // 1.3 Verified card → auto-advances to AI config (UX Spec Rev 2 / B9).
    await waitFor(() =>
      expect(screen.getByText('alex-dev/fast-markdown')).toBeInTheDocument(),
    )
    expect(await screen.findByText(/loading step 2/i)).toBeInTheDocument()

    // 1.4 Configure AI — pick OpenAI card (default), a model, then type the API key.
    expect(
      await screen.findByRole(
        'heading',
        { name: /configure your ai model/i },
        { timeout: 4_000 },
      ),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('option', { name: 'GPT-4o mini' }),
      ).toBeInTheDocument(),
    )
    await user.selectOptions(screen.getByLabelText(/^model/i), 'gpt-4o-mini')
    await user.type(screen.getByLabelText(/api key/i), 'sk-test-key')
    await user.click(screen.getByRole('button', { name: /test and continue/i }))

    // 1.5 Start assessment.
    expect(
      await screen.findByRole('heading', {
        name: /first assessment in progress/i,
      }),
    ).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: /skip to dashboard|go to dashboard/i }),
    )

    // Lands on the dashboard.
    expect(await screen.findByTestId('dashboard-landed')).toBeInTheDocument()
  })

  it('clicking Change on the verified card returns to phase A (token entry)', async () => {
    const user = userEvent.setup()
    renderWizard('/onboarding/connect')

    await user.type(
      screen.getByLabelText(/github personal access token/i),
      'ghp_validtoken',
    )
    await user.click(screen.getByRole('button', { name: /^continue$/i }))

    // The clickable element inside the listbox is the <button> nested in the
    // <li role="option">, not the option itself.
    const pickerRow = await screen.findByRole('button', {
      name: /alex-dev\/fast-markdown/i,
    })
    await user.click(pickerRow)

    await screen.findByText('alex-dev/fast-markdown')
    await user.click(screen.getByRole('button', { name: /change/i }))

    // After Change the token form is visible again — and we have NOT advanced.
    expect(
      screen.getByLabelText(/github personal access token/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /configure your ai model/i }),
    ).not.toBeInTheDocument()
  })

  it('shows the missing-repo-scope error when the picked repo is read-only', async () => {
    const user = userEvent.setup()
    renderWizard('/onboarding/connect')

    await user.type(
      screen.getByLabelText(/github personal access token/i),
      'ghp_validtoken',
    )
    await user.click(screen.getByRole('button', { name: /^continue$/i }))

    // The fast-markdown row is push-capable; the legacy-archive row in the
    // fixture has ``can_push: false`` so RepoPicker disables it. We use the
    // manual-URL fallback to force the missing_repo_scope branch.
    await user.click(screen.getByTestId('manual-url-toggle'))
    await user.type(
      screen.getByTestId('manual-url-input'),
      'https://github.com/alex-dev/read-only-repo',
    )
    await user.click(screen.getByRole('button', { name: /^verify$/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/missing write access|read but not write/i)
  })

  it('shows the invalid-token error from phase A and stays on the token form', async () => {
    const user = userEvent.setup()
    renderWizard('/onboarding/connect')

    await user.type(
      screen.getByLabelText(/github personal access token/i),
      'invalid-token',
    )
    await user.click(screen.getByRole('button', { name: /^continue$/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/token didn't work|read access/i)
    // Still on phase A — token field is visible, picker is not.
    expect(
      screen.getByLabelText(/github personal access token/i),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('repo-picker')).not.toBeInTheDocument()
  })

  it('opens the TokenHowToDialog scrim from the help link', async () => {
    const user = userEvent.setup()
    renderWizard('/onboarding/connect')

    await user.click(
      screen.getByRole('button', { name: /how to create a token/i }),
    )

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(
      screen.getByRole('heading', {
        name: /create a fine-grained github token/i,
      }),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', {
      name: /github\.com\/settings\/personal-access-tokens\/new/i,
    })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
