/**
 * ShareableSummaryCard — the 1200×630 summary artifact.
 *
 * IMPL-0002 Milestone H3. The user never sees this at 1:1 in the browser;
 * `SummaryActionPanel` wraps it in a CSS `transform: scale(...)` preview and
 * `imageExport.ts` captures the true-resolution DOM via this component's
 * forwarded ref.
 *
 * Design invariants (locked by tests):
 *  - Sanctioned gradient exception: `linear-gradient(135deg, #4d44e3 0%,
 *    #575e78 100%)` is the only gradient in the product. Do NOT reuse it.
 *  - White text on the gradient uses `rgba(255,255,255,0.92)` minimum for
 *    WCAG AA contrast. Smaller/faded labels go no lower than 0.92; the
 *    footer Grade pin sits at 0.98.
 *  - The outermost `<div>` is sized 1200×630 and receives the ref. Any
 *    ancestor transform would break html-to-image capture — keep scaling on
 *    the parent wrapper, never on this component.
 */
import { forwardRef } from 'react'

export interface ShareableSummaryCardProps {
  repoName: string
  completedAt: string
  vulnsFixed: number
  postureChecksPassing: number
  prsMerged: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
}

const ShareableSummaryCard = forwardRef<HTMLDivElement, ShareableSummaryCardProps>(
  function ShareableSummaryCard(
    { repoName, completedAt, vulnsFixed, postureChecksPassing, prsMerged, grade },
    ref,
  ) {
    return (
      <div
        ref={ref}
        data-testid="ShareableSummaryCard"
        role="img"
        aria-label={`Cliff security summary for ${repoName}`}
        style={{
          width: '1200px',
          height: '630px',
          background:
            'linear-gradient(135deg, #4d44e3 0%, #575e78 100%)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            padding: '40px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            color: '#ffffff',
          }}
        >
          {/* Header — eyebrow + repo + completion date, shield right-aligned */}
          <div className="flex items-start justify-between">
            <div>
              <p
                className="font-body text-xs font-semibold uppercase"
                style={{
                  color: 'rgba(255,255,255,0.92)',
                  letterSpacing: '0.22em',
                }}
              >
                Cliff · Security summary
              </p>
              <h4
                className="font-headline text-3xl font-extrabold"
                style={{ marginTop: '12px', color: '#ffffff' }}
              >
                {repoName}
              </h4>
              <p
                className="text-sm"
                style={{ marginTop: '4px', color: 'rgba(255,255,255,0.95)' }}
              >
                Completed {completedAt}
              </p>
            </div>
            {/* Small decorative shield (ghost white on the gradient) */}
            <svg viewBox="0 0 64 76" width="56" height="64" aria-hidden="true">
              <path
                d="M32 2 L60 12 V40 C60 56 48 68 32 74 C16 68 4 56 4 40 V12 Z"
                fill="#ffffff"
                fillOpacity="0.14"
                stroke="#ffffff"
                strokeOpacity="0.4"
                strokeWidth="1"
              />
              <path
                d="M24 40 L30 46 L42 34"
                stroke="#ffffff"
                strokeWidth="3"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          {/* Footer — stats grid, divider, generated-by row */}
          <div>
            <div
              className="grid grid-cols-3"
              style={{ gap: '24px', marginBottom: '28px' }}
            >
              <div>
                <p
                  className="font-headline text-3xl font-extrabold"
                  style={{ lineHeight: 1, color: '#ffffff' }}
                >
                  {vulnsFixed}
                </p>
                <p
                  className="uppercase"
                  style={{
                    marginTop: '6px',
                    fontSize: '11px',
                    letterSpacing: '0.1em',
                    color: 'rgba(255,255,255,0.92)',
                  }}
                >
                  Vulns fixed
                </p>
              </div>
              <div>
                <p
                  className="font-headline text-3xl font-extrabold"
                  style={{ lineHeight: 1, color: '#ffffff' }}
                >
                  {postureChecksPassing}
                </p>
                <p
                  className="uppercase"
                  style={{
                    marginTop: '6px',
                    fontSize: '11px',
                    letterSpacing: '0.1em',
                    color: 'rgba(255,255,255,0.92)',
                  }}
                >
                  Posture checks
                </p>
              </div>
              <div>
                <p
                  className="font-headline text-3xl font-extrabold"
                  style={{ lineHeight: 1, color: '#ffffff' }}
                >
                  {prsMerged}
                </p>
                <p
                  className="uppercase"
                  style={{
                    marginTop: '6px',
                    fontSize: '11px',
                    letterSpacing: '0.1em',
                    color: 'rgba(255,255,255,0.92)',
                  }}
                >
                  PRs merged
                </p>
              </div>
            </div>
            <div
              style={{
                height: '1px',
                background: 'rgba(255,255,255,0.30)',
                marginBottom: '16px',
              }}
            />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <p
                className="text-xs"
                style={{ color: 'rgba(255,255,255,0.92)' }}
              >
                Generated by Cliff · cliff.dev
              </p>
              <p
                className="text-xs font-semibold"
                style={{ color: 'rgba(255,255,255,0.98)' }}
              >
                Grade {grade}
              </p>
            </div>
          </div>
        </div>
      </div>
    )
  },
)

export default ShareableSummaryCard
