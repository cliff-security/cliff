import { describe, expect, it } from 'vitest'
import { countQuickWins } from '../quickWins'

describe('countQuickWins', () => {
  it('returns 0 for null / undefined / empty level-up data', () => {
    expect(countQuickWins(null)).toBe(0)
    expect(countQuickWins(undefined)).toBe(0)
    expect(countQuickWins({ gates: [] })).toBe(0)
  })

  it('sums auto_fixable_check_names only across auto_fixable gates', () => {
    const levelUp = {
      gates: [
        {
          status: 'auto_fixable',
          auto_fixable_check_names: ['code_owners_exists', 'security_md'],
        },
        {
          status: 'auto_fixable',
          auto_fixable_check_names: ['secret_scanning_enabled'],
        },
        // a todo gate with names present is NOT counted
        { status: 'todo', auto_fixable_check_names: ['branch_protection'] },
        // a gate with no names
        { status: 'in_progress' },
      ],
    }
    expect(countQuickWins(levelUp)).toBe(3)
  })

  it('agrees with the LevelUp panel: 0 auto_fixable gates → 0 quick wins', () => {
    const levelUp = {
      gates: [
        { status: 'todo', auto_fixable_check_names: [] },
        { status: 'ready_to_review' },
      ],
    }
    expect(countQuickWins(levelUp)).toBe(0)
  })
})
