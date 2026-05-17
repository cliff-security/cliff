/**
 * ShieldSVG — the "Secured by Cliff" badge.
 *
 * Three sanctioned sizes:
 *  - 150×180 — the celebration overlay hero (default)
 *  - 80×96 — the dashboard aside (shield-as-button affordance)
 *  - 56×64 — the small ghost shield inside ShareableSummaryCard (but that
 *    card inlines its own miniature; this component is for the primary
 *    indigo shield surface)
 *
 * Caption: "COMPLETED {date}" — hardcoded prefix, date comes from props.
 *
 * Accessibility:
 *  - Default: role="img" + descriptive aria-label for screen readers.
 *  - When purely decorative (e.g. inside a button that already has its own
 *    aria-label), pass `ariaHidden` to remove it from the a11y tree.
 */

export interface ShieldSVGProps {
  /** e.g. "2026-04-14" — displayed verbatim after the "COMPLETED" prefix. */
  completedDate: string
  /** Width in pixels. Default 150. */
  width?: number
  /** Height in pixels. Default 180. */
  height?: number
  /** Mark as decorative (use when the parent owns the accessible name). */
  ariaHidden?: boolean
}

export default function ShieldSVG({
  completedDate,
  width = 150,
  height = 180,
  ariaHidden = false,
}: ShieldSVGProps) {
  const a11yProps = ariaHidden
    ? { 'aria-hidden': true as const }
    : { role: 'img' as const, 'aria-label': 'Secured by Cliff' }

  return (
    <svg
      viewBox="0 0 160 190"
      width={width}
      height={height}
      style={{ filter: 'drop-shadow(0 6px 18px rgba(77,68,227,0.35))' }}
      {...a11yProps}
    >
      {/* Indigo shield body */}
      <path
        d="M80 6 L150 30 V96 C150 140 122 168 80 186 C38 168 10 140 10 96 V30 Z"
        fill="#4d44e3"
      />
      {/* Hairline inner rim */}
      <path
        d="M80 6 L150 30 V96 C150 140 122 168 80 186 C38 168 10 140 10 96 V30 Z"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.15"
        strokeWidth="1"
      />
      {/* SECURED / by Cliff wordmark */}
      <text
        x="80"
        y="70"
        textAnchor="middle"
        fill="#ffffff"
        fontFamily="Manrope, sans-serif"
        fontWeight="700"
        fontSize="12"
        letterSpacing="1.5"
      >
        SECURED
      </text>
      <text
        x="80"
        y="88"
        textAnchor="middle"
        fill="#ffffff"
        fontFamily="Manrope, sans-serif"
        fontWeight="800"
        fontSize="16"
      >
        by Cliff
      </text>
      {/* Check ring + check */}
      <circle cx="80" cy="122" r="22" fill="#ffffff" fillOpacity="0.14" />
      <path
        d="M68 122 L78 132 L94 114"
        stroke="#ffffff"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Caption — COMPLETED {date} */}
      <text
        x="80"
        y="166"
        textAnchor="middle"
        fill="#ffffff"
        fillOpacity="0.7"
        fontFamily="Inter, sans-serif"
        fontWeight="500"
        fontSize="8"
        letterSpacing="1"
      >
        COMPLETED {completedDate}
      </text>
    </svg>
  )
}
