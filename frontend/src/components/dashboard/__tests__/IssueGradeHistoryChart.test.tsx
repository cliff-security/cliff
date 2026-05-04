import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IssueGradeHistoryChart from '../IssueGradeHistoryChart'
import { findPromotion } from '../findPromotion'

const ZERO_60 = Array<number>(60).fill(0)

function gradeArray(spec: Array<{ at: number; grade: 'A' | 'B' | 'C' | 'D' | 'F' }>) {
  // Build a 90-day array oldest-first; spec uses indices from the end.
  const arr: Array<{ date: string; grade: 'A' | 'B' | 'C' | 'D' | 'F' | null }> = []
  for (let i = 0; i < 90; i += 1) arr.push({ date: `2026-01-${i}`, grade: null })
  spec.forEach(({ at, grade }) => {
    arr[arr.length - 1 - at].grade = grade
  })
  return arr
}

describe('<IssueGradeHistoryChart />', () => {
  it('renders nothing when severityHistory is null', () => {
    const { container } = render(
      <IssueGradeHistoryChart severityHistory={null} gradeHistory={[]} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when every severity bucket is all-zero', () => {
    const { container } = render(
      <IssueGradeHistoryChart
        severityHistory={{
          critical: ZERO_60,
          high: ZERO_60,
          medium: ZERO_60,
          low: ZERO_60,
        }}
        gradeHistory={[]}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders four stacked area paths plus a total line when data is present', () => {
    const sev = {
      critical: [...ZERO_60.slice(0, 59), 1],
      high: [...ZERO_60.slice(0, 59), 2],
      medium: [...ZERO_60.slice(0, 59), 3],
      low: [...ZERO_60.slice(0, 59), 4],
    }
    render(<IssueGradeHistoryChart severityHistory={sev} gradeHistory={[]} />)
    const svg = screen.getByTestId('issue-grade-history-chart')
    // 4 area bands + 1 total line ⇒ at least 5 paths.
    expect(svg.querySelectorAll('path').length).toBeGreaterThanOrEqual(5)
  })

  it('renders the promotion marker when grade history shows a recent change', () => {
    const sev = {
      critical: ZERO_60,
      high: ZERO_60,
      medium: [...ZERO_60.slice(0, 59), 5],
      low: ZERO_60,
    }
    // Today: A, 17 days ago: B.
    const grade = gradeArray([
      { at: 0, grade: 'A' },
      { at: 17, grade: 'B' },
    ])
    render(<IssueGradeHistoryChart severityHistory={sev} gradeHistory={grade} />)
    expect(screen.getByTestId('issue-grade-history-promotion')).toBeInTheDocument()
    expect(screen.getByText(/B → A · 17d ago/)).toBeInTheDocument()
  })

  it('does not render a promotion marker when grade history is flat', () => {
    const sev = {
      critical: ZERO_60,
      high: ZERO_60,
      medium: [...ZERO_60.slice(0, 59), 1],
      low: ZERO_60,
    }
    const grade = gradeArray([
      { at: 0, grade: 'B' },
      { at: 30, grade: 'B' },
    ])
    render(<IssueGradeHistoryChart severityHistory={sev} gradeHistory={grade} />)
    expect(screen.queryByTestId('issue-grade-history-promotion')).toBeNull()
  })
})

describe('findPromotion()', () => {
  it('returns null when grade_history is empty', () => {
    expect(findPromotion([], 60)).toBeNull()
  })

  it('finds a promotion when the most recent letter differs from the previous non-null letter', () => {
    const grade = gradeArray([
      { at: 0, grade: 'A' },
      { at: 5, grade: 'A' },
      { at: 17, grade: 'C' },
    ])
    const result = findPromotion(grade, 60)
    expect(result).not.toBeNull()
    expect(result?.toLetter).toBe('A')
    expect(result?.fromLetter).toBe('C')
    expect(result?.daysAgo).toBe(17)
  })
})
