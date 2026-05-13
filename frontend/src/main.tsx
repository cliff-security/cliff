import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import { queryClient } from '@/lib/query-client'
import { router } from '@/router'
import './index.css'
import './styles/cyberdeck.css'

/**
 * In dev, stand up the MSW service worker for the handful of routes that don't
 * yet have a real backend (Findings list + detail). Everything else goes
 * through the Vite proxy to FastAPI. Production skips this entirely.
 *
 * Set `VITE_USE_REAL_API=1` (or `VITE_MSW=off`) to bypass the worker and let
 * every request through to the backend.
 */
async function startMockApi(): Promise<void> {
  if (!import.meta.env.DEV) return
  if (import.meta.env.VITE_USE_REAL_API) return
  if (import.meta.env.VITE_MSW === 'off') return
  try {
    const { worker } = await import('@/mocks/browser')
    await worker.start({
      onUnhandledRequest: 'bypass',
      serviceWorker: { url: '/mockServiceWorker.js' },
    })
  } catch (err) {
    // Non-fatal: fall through to rendering so the app still boots.
    console.error('MSW worker failed to start', err)
  }
}

function renderApp() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  )
}

void startMockApi().finally(renderApp)
