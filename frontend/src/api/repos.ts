/**
 * Repo Project-profile fetchers + hooks (ADR-0053 / PRD-0009).
 *
 * Surfaces the per-repo profile freshness for the dashboard card and the
 * re-profile action. The backend resolves "the current repo" from the GitHub
 * integration, so the read path needs no argument.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './client'

export type RepoProfileStatusValue =
  | 'none'
  | 'building'
  | 'ready'
  | 'stale'
  | 'error'

export interface RepoProfileStatus {
  repo_url: string | null
  status: RepoProfileStatusValue
  profiled_at: string | null
  last_profiled_sha: string | null
  profile_md: string | null
}

export interface RebuildResponse {
  status: 'scheduled' | 'skipped'
  repo_url: string | null
  reason?: string | null
}

export const reposApi = {
  getProfile: () => request<RepoProfileStatus>('/api/repos/profile'),
  rebuildProfile: (repoUrl?: string) =>
    request<RebuildResponse>('/api/repos/profile/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(repoUrl ? { repo_url: repoUrl } : {}),
    }),
}

export function useRepoProfile() {
  return useQuery({
    queryKey: ['repo-profile'],
    queryFn: reposApi.getProfile,
    // While a profile is building, poll so the card flips to ready on its own.
    refetchInterval: (query) =>
      query.state.data?.status === 'building' ? 2_000 : false,
  })
}

export function useRebuildProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (repoUrl?: string) => reposApi.rebuildProfile(repoUrl),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['repo-profile'] }),
  })
}
