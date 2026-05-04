/**
 * findPromotion — locate the most-recent grade-letter change in a daily
 * grade-history series. Used by IssueGradeHistoryChart to position the
 * dotted promotion marker; exposed in its own module so the chart file
 * stays exports-components-only (HMR-safe).
 */
import type { components } from '@/api/types'

type GradeLetter = 'A' | 'B' | 'C' | 'D' | 'F'
type GradeHistoryPoint = components['schemas']['GradeHistoryPoint']

export const GRADE_ORDER: Record<GradeLetter, number> = {
  F: 0,
  D: 1,
  C: 2,
  B: 3,
  A: 4,
}

export interface PromotionMark {
  index: number // index in the severity-history window
  fromLetter: GradeLetter | null
  toLetter: GradeLetter | null
  daysAgo: number // days back from the latest entry
}

export function findPromotion(
  gradeHistory: GradeHistoryPoint[] | undefined,
  severityWindow: number,
): PromotionMark | null {
  if (!gradeHistory || gradeHistory.length === 0) return null
  // Walk backwards from "today" looking for the last day where the grade
  // changed compared to the previous non-null grade.
  const reversed = [...gradeHistory].reverse()
  let currentLetter: GradeLetter | null = null
  let previousLetter: GradeLetter | null = null
  let changeIdxFromEnd = -1

  for (let i = 0; i < reversed.length; i += 1) {
    const g = (reversed[i].grade as GradeLetter | null) ?? null
    if (g === null) continue
    if (currentLetter === null) {
      currentLetter = g
      continue
    }
    if (g !== currentLetter) {
      previousLetter = g
      changeIdxFromEnd = i
      break
    }
  }
  if (changeIdxFromEnd === -1 || currentLetter === null) return null

  const daysAgo = changeIdxFromEnd
  // Map onto the severity window. Anything older than the window is
  // pinned to index 0.
  const idx = Math.max(0, severityWindow - 1 - daysAgo)
  return {
    index: idx,
    fromLetter: previousLetter,
    toLetter: currentLetter,
    daysAgo,
  }
}
