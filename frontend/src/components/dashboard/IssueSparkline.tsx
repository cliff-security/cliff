/**
 * IssueSparkline — inline SVG trend line + filled area + endpoint dot.
 *
 * Mirrors ``IPSparkline`` from the PRD-0006 design handoff. Default size
 * 120×36; renders ``null`` for empty/undefined data so callers can drop it
 * straight into a card without a manual guard.
 */
type Numeric = number | null

export default function IssueSparkline({
  data,
  width = 120,
  height = 36,
  color = 'var(--primary, #4d44e3)',
  fillOpacity = 0.12,
}: {
  data: Numeric[] | undefined
  width?: number
  height?: number
  color?: string
  fillOpacity?: number
}) {
  if (!data || data.length === 0) return null
  const numeric = data.filter((v): v is number => typeof v === 'number')
  if (numeric.length === 0) return null

  const min = Math.min(...numeric)
  const max = Math.max(...numeric)
  const range = max - min || 1
  const points = data.map((d, i): [number, number] => {
    const x = (i / (data.length - 1)) * width
    const value = typeof d === 'number' ? d : min
    const y = height - ((value - min) / range) * (height - 4) - 2
    return [x, y]
  })
  const linePath = points
    .map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`))
    .join(' ')
  const areaPath = `${linePath} L${width},${height} L0,${height} Z`
  const last = points[points.length - 1]

  return (
    <svg
      data-testid="issue-sparkline"
      width={width}
      height={height}
      style={{ display: 'block', overflow: 'visible' }}
      aria-hidden
    >
      <path d={areaPath} fill={color} opacity={fillOpacity} />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill={color} />
    </svg>
  )
}
