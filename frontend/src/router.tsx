import { createBrowserRouter, Navigate } from 'react-router'
import AppLayout from '@/layouts/AppLayout'
import OnboardingGate from '@/components/OnboardingGate'
import FirstRunRedirect from '@/components/FirstRunRedirect'
import DashboardPage from '@/pages/DashboardPage'
import FindingDetailPage from '@/pages/FindingDetailPage'
import { FindingDetailPageRedirect } from '@/pages/FindingsRedirects'
import IssuesPage from '@/pages/IssuesPage'
import WorkspaceRedirect from '@/pages/WorkspaceRedirect'
import SettingsPage from '@/pages/SettingsPage'
import Welcome from '@/pages/onboarding/Welcome'
import ConnectRepo from '@/pages/onboarding/ConnectRepo'
import ConfigureAI from '@/pages/onboarding/ConfigureAI'
import StartAssessment from '@/pages/onboarding/StartAssessment'

const gated = (page: React.ReactElement) => (
  <OnboardingGate>{page}</OnboardingGate>
)

export const router = createBrowserRouter([
  // Onboarding wizard — full-bleed, lives outside AppLayout per UX spec.
  { path: '/onboarding', element: <Navigate to="/onboarding/welcome" replace /> },
  { path: '/onboarding/welcome', element: gated(<Welcome />) },
  { path: '/onboarding/connect', element: gated(<ConnectRepo />) },
  { path: '/onboarding/ai', element: gated(<ConfigureAI />) },
  { path: '/onboarding/start', element: gated(<StartAssessment />) },

  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        index: true,
        element: (
          <FirstRunRedirect>
            <IssuesPage />
          </FirstRunRedirect>
        ),
      },
      { path: 'dashboard', element: <DashboardPage /> },
      // PRD-0006 Phase 1 — Findings page is renamed to Issues. The legacy
      // /findings route(s) redirect so existing bookmarks keep working.
      { path: 'issues', element: <IssuesPage /> },
      { path: 'issues/:id', element: <FindingDetailPage /> },
      { path: 'findings', element: <Navigate to="/issues" replace /> },
      { path: 'findings/:id', element: <FindingDetailPageRedirect /> },
      { path: 'queue', element: <Navigate to="/issues" replace /> },
      // PRD-0006 Phase 2 — the standalone Workspace page is removed; the
      // 480px side panel on /issues is now the only depth surface. The
      // bare /workspace path goes straight to /issues; /workspace/:id
      // resolves the workspace, then redirects to ?open=<finding_id>.
      { path: 'workspace', element: <Navigate to="/issues" replace /> },
      { path: 'workspace/:id', element: <WorkspaceRedirect /> },
      // /history was removed (closed findings live at the bottom of /issues).
      { path: 'history', element: <Navigate to="/issues" replace /> },
      { path: 'integrations', element: <Navigate to="/settings" replace /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
])
