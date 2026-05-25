/**
 * countQuickWins — derive the dashboard hero's "Quick wins" stat from the
 * same level-up gate data the LevelUpPanel renders (B10).
 *
 * Before this, the AssessmentSummary hero hard-coded ``quickWins: 0`` while
 * the LevelUpPanel correctly listed auto-fixable posture checks — two
 * surfaces, two truths. Reading both off ``level_up.gates`` makes them
 * impossible to disagree.
 */

type GateLike = {
  status?: string | null
  auto_fixable_check_names?: string[] | null
}

type LevelUpLike = {
  gates?: GateLike[] | null
} | null | undefined

export function countQuickWins(levelUp: LevelUpLike): number {
  const gates = levelUp?.gates ?? []
  let total = 0
  for (const g of gates) {
    if (g.status === 'auto_fixable') {
      total += g.auto_fixable_check_names?.length ?? 0
    }
  }
  return total
}
