import { describe, expect, it } from 'vitest'
import { canRunAnsible } from './useAnsibleRunners'

describe('composables/useAnsibleRunners', () => {
  it('treats an agent that reports nothing as unknown, not empty', () => {
    // An agent that predates the heartbeat field says nothing about its
    // abilities — blocking it would break every Ansible run until the fleet
    // is updated.
    expect(canRunAnsible(undefined)).toBe(true)
    expect(canRunAnsible(null)).toBe(true)
    expect(canRunAnsible([])).toBe(true)
  })

  it('blocks an agent that reports capabilities without ANSIBLE_PLAYBOOK', () => {
    expect(canRunAnsible(['SERVICE', 'FILE'])).toBe(false)
  })

  it('allows an agent that reports ANSIBLE_PLAYBOOK', () => {
    expect(canRunAnsible(['SERVICE', 'ANSIBLE_PLAYBOOK'])).toBe(true)
  })
})
