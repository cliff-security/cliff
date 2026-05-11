import { Outlet } from 'react-router'
import SideNav from '@/components/layout/SideNav'
import { AIProviderModalProvider } from '@/components/ai-provider'

/**
 * App chrome — ``SideNav`` in flow on the left, ``<Outlet />`` for the page.
 *
 * PRD-0004 Story 0 retires ``TopBar`` entirely: its only tenants (search,
 * notifications bell, help) were non-functional placeholders. Each page
 * component now owns its own title row via ``PageShell``.
 *
 * IMPL-0008 puts the 224px sidebar in normal flex flow (no fixed
 * positioning, no ``ml-20`` offset). ``min-w-0`` on the main column lets it
 * shrink so long strings don't push the layout. ``overflow-x-clip`` on the
 * outer div + ``overflow-x-hidden`` on the scrolling column preserve the
 * B10 dogfood fix — long strings inside a posture card (branch-protection
 * API responses, etc.) can't widen the page.
 */
export default function AppLayout() {
  return (
    <AIProviderModalProvider>
      <div className="flex min-h-screen overflow-x-clip">
        <SideNav />
        <main className="flex-1 min-w-0 overflow-x-hidden">
          <Outlet />
        </main>
      </div>
    </AIProviderModalProvider>
  )
}
