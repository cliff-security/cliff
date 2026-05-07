/**
 * AssessmentFailedCard — surfaces *why* an assessment ended in `failed`.
 *
 * Backend migration 015 / API: `assessment.error_kind`, `error_message`,
 * `error_details`, `failed_step`. Friendly headline + step copy come from
 * those fields; the raw `error_details` lives behind a "Show technical
 * details" disclosure so non-technical users see a calm card while engineers
 * can self-debug without spinning up a second tool.
 *
 * Design system: reuses the `InlineErrorCallout` tonal palette
 * (`bg-error-container/20`, ghost border at 15% opacity, sentence case) per
 * the Serene Sentinel rules in CLAUDE.md.
 */

import { useState } from 'react'

export type AssessmentFailedStep =
  | 'clone'
  | 'detect'
  | 'trivy_vuln'
  | 'trivy_secret'
  | 'semgrep'
  | 'posture'
  | 'descriptions'
  | 'persist'
  | 'unknown'

export interface AssessmentFailedCardProps {
  message: string
  failedStep?: AssessmentFailedStep | null
  details?: string | null
  retrying?: boolean
  onRetry: () => void
}

const STEP_LABEL: Record<AssessmentFailedStep, string> = {
  clone: 'while cloning the repository',
  detect: 'while preparing the repository',
  trivy_vuln: 'while scanning dependencies',
  trivy_secret: 'while scanning for secrets',
  semgrep: 'while running static analysis',
  posture: 'while checking repository posture',
  descriptions: 'while finalizing the report',
  persist: 'while saving results',
  unknown: '',
}

export default function AssessmentFailedCard({
  message,
  failedStep,
  details,
  retrying = false,
  onRetry,
}: AssessmentFailedCardProps) {
  const [showDetails, setShowDetails] = useState(false)
  const stepCopy =
    failedStep && failedStep !== 'unknown' ? STEP_LABEL[failedStep] : ''

  return (
    <section
      role="alert"
      aria-live="polite"
      data-testid="assessment-failed-card"
      className="rounded-3xl bg-error-container/20 px-8 py-8"
    >
      <div className="flex items-start gap-4">
        <span
          className="material-symbols-outlined text-error flex-shrink-0"
          style={{ fontSize: 28 }}
          aria-hidden="true"
        >
          error
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-headline text-xl font-bold text-on-surface">
            {message}
          </h2>
          {stepCopy && (
            <p
              className="mt-1 text-sm text-on-surface-variant"
              data-testid="assessment-failed-step"
            >
              The assessment stopped {stepCopy}.
            </p>
          )}

          {details && (
            <details
              className="mt-4"
              open={showDetails}
              onToggle={(e) =>
                setShowDetails((e.target as HTMLDetailsElement).open)
              }
              data-testid="assessment-failed-details"
            >
              <summary className="cursor-pointer select-none text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 rounded">
                {showDetails ? 'Hide technical details' : 'Show technical details'}
              </summary>
              <pre
                className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant"
                data-testid="assessment-failed-details-pre"
              >
                {details}
              </pre>
            </details>
          )}

          <div className="mt-6 flex items-center gap-3">
            <button
              type="button"
              data-testid="assessment-failed-retry"
              disabled={retrying}
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              aria-busy={retrying}
            >
              {retrying ? (
                <span
                  className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-on-primary/40 border-t-on-primary"
                  aria-hidden
                />
              ) : (
                <span
                  className="material-symbols-outlined text-sm"
                  aria-hidden
                >
                  refresh
                </span>
              )}
              {retrying ? 'Retrying…' : 'Try again'}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
