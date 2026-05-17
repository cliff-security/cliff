/**
 * Typed accessor for the handful of values the onboarding wizard stashes
 * in sessionStorage between pages. Centralised so the keys are declared
 * once and can be cleared together on success or abandon.
 */
const PREFIX = 'cliff.onboarding.'

const KEYS = {
  assessmentId: `${PREFIX}assessment_id`,
  repoUrl: `${PREFIX}repo_url`,
  provider: `${PREFIX}provider`,
  model: `${PREFIX}model`,
} as const

export type OnboardingField = keyof typeof KEYS

export const onboardingStorage = {
  get(field: OnboardingField): string | null {
    return sessionStorage.getItem(KEYS[field])
  },
  set(field: OnboardingField, value: string): void {
    sessionStorage.setItem(KEYS[field], value)
  },
  clear(): void {
    for (const key of Object.values(KEYS)) sessionStorage.removeItem(key)
  },
}
