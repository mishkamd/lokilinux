import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import OsDistributionDonut from './OsDistributionDonut.vue'

describe('dashboard/OsDistributionDonut', () => {
  it('lists the OS mix with counts and shares, dropping empty entries', async () => {
    const wrapper = await mountSuspended(OsDistributionDonut, {
      props: { distribution: { Ubuntu: 3, Debian: 1, Unknown: 0 } },
    })
    expect(wrapper.text()).toContain('Ubuntu')
    expect(wrapper.text()).toContain('75%')
    expect(wrapper.text()).not.toContain('Unknown')
  }, 20000)

  it('shows the empty state when no agent has reported an OS', async () => {
    const wrapper = await mountSuspended(OsDistributionDonut, {
      props: { distribution: {} },
    })
    expect(wrapper.text()).toContain('No servers registered.')
  }, 20000)
})
