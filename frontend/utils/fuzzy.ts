/**
 * Subsequence match: every character of `query` appears in `text`, in order.
 * Returns a score (lower is better) or `null` when the query does not match.
 *
 * Deliberately tiny — the command palette needs ranking, not a search engine.
 * Consecutive hits and early hits score better, so "cmp" finds
 * "Compliance ▸ Policy Sets" before "Components".
 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase().trim()
  if (!q) return 0
  const t = text.toLowerCase()
  let qi = 0
  let score = 0
  let last = -1
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) {
      score += last === i - 1 ? 0 : 1 // a gap costs
      if (last === -1) score += i * 0.1 // early hits are cheaper
      last = i
      qi++
    }
  }
  if (qi < q.length) return null
  return score + t.length * 0.01 // prefer the shorter label
}
