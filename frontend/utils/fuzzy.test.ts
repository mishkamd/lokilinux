import { describe, expect, it } from 'vitest'
import { fuzzyScore } from './fuzzy'

describe('fuzzyScore', () => {
  it('matches a subsequence and rejects a missing one', () => {
    expect(fuzzyScore('cmp', 'Compliance')).not.toBeNull()
    expect(fuzzyScore('zzz', 'Compliance')).toBeNull()
  })

  it('is case insensitive and ignores surrounding space', () => {
    expect(fuzzyScore('  HOST ', 'web-01')).toBe(fuzzyScore('host', 'web-01'))
  })

  it('ranks a contiguous match above a scattered one', () => {
    const tight = fuzzyScore('pol', 'Policies')!
    const loose = fuzzyScore('pol', 'Penalty Output List')!
    expect(tight).toBeLessThan(loose)
  })

  it('scores an empty query as a match', () => {
    expect(fuzzyScore('', 'anything')).toBe(0)
  })
})
