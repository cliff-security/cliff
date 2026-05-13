import { Outlet } from 'react-router'
import SideNav from '@/components/layout/SideNav'
import { AIProviderModalProvider } from '@/components/ai-provider'

/**
 * App chrome — ``SideNav`` in flow on the left, ``<Outlet />`` for the page.
 *
 * Critique fix: the sticky page topbar (PageShell `<header>`) was breaking
 * because the previous ``overflow-x-clip`` / ``overflow-x-hidden`` on the
 * layout containers made `<main>` the nearest scroll context for any
 * ``position: sticky`` child. The header stuck to ``<main>`` instead of
 * the viewport, so scrolling slid the title strip out of view.
 *
 * Fix: put the vertical scroll on ``<main>`` itself (`overflow-y: auto;
 * height: 100vh`) and let it horizontally clip with ``overflow-x: clip``.
 * Sticky children now bind to ``<main>``'s scroll, which is exactly the
 * scroll the user sees — so ``position: sticky; top: 0`` pins to the
 * top of the visible page region. The B10 dogfood fix (long strings
 * inside posture cards can't widen the layout) is preserved by the
 * `overflow-x: clip` on `<main>`.
 */
export default function AppLayout() {
  return (
    <AIProviderModalProvider>
      <div className="flex min-h-screen">
        <SideNav />
        <main
          className="flex-1 min-w-0"
          style={{
            height: '100vh',
            overflowY: 'auto',
            overflowX: 'clip',
          }}
        >
          <Outlet />
        </main>
      </div>
    </AIProviderModalProvider>
  )
}
