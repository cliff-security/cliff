/**
 * Thin fetch wrapper for the onboarding endpoints. Mirrors the OpenAPI
 * contract in `src/api/types.ts`:
 *   POST /api/onboarding/repo          — verify repo + PAT
 *   POST /api/onboarding/github/repos  — list the PAT's reachable repos (picker)
 *   POST /api/onboarding/complete      — mark onboarding complete
 */

const BASE = ''

export interface OnboardingRepoRequest {
  repo_url: string
  /** Optional. Omitted by the App + Device Flow path — when absent
   *  the backend reads the user access token from the vault. */
  github_token?: string
}

/** Display-only metadata for the verified-connection card (frame 1.3).
 *  The backend populates this from a GitHub REST probe on ``/onboarding/repo``
 *  and returns ``verified=None`` if GitHub declines (network, 4xx, etc.);
 *  the UI renders a minimal fallback in that case. */
export interface VerifiedRepoSummary {
  repo_name: string
  visibility: 'public' | 'private' | string
  default_branch: string
  permissions?: string[]
}

export interface OnboardingRepoResponse {
  assessment_id: string
  repo_url: string
  verified?: VerifiedRepoSummary
}

export interface ListReposRequest {
  /** Optional. Omitted by the App + Device Flow path — when absent
   *  the backend reads the user access token from the vault. */
  github_token?: string
}

/** One row in the onboarding repo picker. ``can_push`` mirrors GitHub's
 *  repo ``permissions.push`` so we can disable rows for read-only repos
 *  rather than letting the user pick one and surface the failure later. */
export interface RepoOption {
  full_name: string
  html_url: string
  private: boolean
  default_branch: string
  can_push: boolean
}

export interface ListReposResponse {
  repos: RepoOption[]
}

export interface OnboardingCompleteRequest {
  assessment_id: string
}

export interface OnboardingCompleteResponse {
  onboarding_completed: boolean
}

export class OnboardingApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'OnboardingApiError'
    this.status = status
    this.code = code
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    let code: string | undefined
    try {
      const data = await resp.json()
      if (typeof data?.detail === 'string') detail = data.detail
      if (typeof data?.code === 'string') code = data.code
    } catch {
      /* non-JSON error body */
    }
    throw new OnboardingApiError(detail, resp.status, code)
  }
  return resp.json() as Promise<T>
}

export const onboardingApi = {
  connectRepo: (req: OnboardingRepoRequest) =>
    postJson<OnboardingRepoResponse>('/api/onboarding/repo', req),

  listRepos: (req: ListReposRequest) =>
    postJson<ListReposResponse>('/api/onboarding/github/repos', req),

  // GitHub App + Device Flow path (ADR-0035, IMPL-0010): the user has
  // already authorized the App and the user access token lives in the
  // vault, so these helpers omit the token from the request — the
  // backend route detects the missing field and falls back to the
  // vault token.
  listReposFromVault: () =>
    postJson<ListReposResponse>('/api/onboarding/github/repos', {}),

  connectRepoFromVault: (repo_url: string) =>
    postJson<OnboardingRepoResponse>('/api/onboarding/repo', { repo_url }),

  complete: (req: OnboardingCompleteRequest) =>
    postJson<OnboardingCompleteResponse>('/api/onboarding/complete', req),
}
