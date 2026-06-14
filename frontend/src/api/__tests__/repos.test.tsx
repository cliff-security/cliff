import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '../../mocks/server'
import { reposApi, useRepoProfile } from '../repos'

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
  }
}

const READY = {
  repo_url: 'https://github.com/acme/web',
  status: 'ready',
  profiled_at: '2026-06-10T00:00:00Z',
  last_profiled_sha: 'abcdef1234567890',
  profile_md: '# Project profile\n- **summary:** A self-hosted web service.\n',
}

describe('reposApi', () => {
  it('getProfile hits /api/repos/profile', async () => {
    server.use(http.get('/api/repos/profile', () => HttpResponse.json(READY)))
    const profile = await reposApi.getProfile()
    expect(profile.status).toBe('ready')
    expect(profile.repo_url).toContain('acme/web')
    expect(profile.last_profiled_sha).toBe('abcdef1234567890')
  })

  it('rebuildProfile posts to /api/repos/profile/rebuild', async () => {
    server.use(
      http.post('/api/repos/profile/rebuild', () =>
        HttpResponse.json({ status: 'scheduled', repo_url: READY.repo_url }),
      ),
    )
    const res = await reposApi.rebuildProfile()
    expect(res.status).toBe('scheduled')
  })
})

describe('useRepoProfile', () => {
  it('resolves the none state', async () => {
    server.use(
      http.get('/api/repos/profile', () =>
        HttpResponse.json({
          repo_url: null,
          status: 'none',
          profiled_at: null,
          last_profiled_sha: null,
          profile_md: null,
        }),
      ),
    )
    const { result } = renderHook(() => useRepoProfile(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.status).toBe('none')
  })
})
