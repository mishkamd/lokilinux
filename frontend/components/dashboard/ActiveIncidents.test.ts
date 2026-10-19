import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import ActiveIncidents from './ActiveIncidents.vue'
import type { Alert, InventoryServer } from '~/stores/dashboard'

const AGENT_ID = '7d9c1a2e-0000-4000-8000-000000000001'

function alert(overrides: Partial<Alert> = {}): Alert {
  const now = new Date().toISOString()
  return {
    id: 'alert-1',
    title: 'Disk almost full',
    description: null,
    severity: 'HIGH',
    status: 'ACTIVE',
    alert_type: 'disk',
    agent_id: AGENT_ID,
    hostname: null,
    triggered_at: now,
    created_at: now,
    ...overrides,
  }
}

const inventory: InventoryServer[] = [{
  id: AGENT_ID, hostname: 'inv-db-07', os_name: null, status: 'ACTIVE',
  ip_address: null, category_id: null, last_seen_at: null, cve_count: 0,
}]

describe('dashboard/ActiveIncidents hostname', () => {
  it('shows the alert hostname in preference to the inventory name', async () => {
    const wrapper = await mountSuspended(ActiveIncidents, {
      props: { incidents: [alert({ hostname: 'web-01' })], inventory },
    })
    expect(wrapper.text()).toContain('web-01')
    expect(wrapper.text()).not.toContain('inv-db-07')
  })

  it('falls back to the inventory name when the alert hostname is null', async () => {
    const wrapper = await mountSuspended(ActiveIncidents, {
      props: { incidents: [alert({ hostname: null })], inventory },
    })
    expect(wrapper.text()).toContain('inv-db-07')
  })

  it('falls back to the raw agent id when neither the alert nor the inventory knows the host', async () => {
    const wrapper = await mountSuspended(ActiveIncidents, {
      props: { incidents: [alert({ hostname: null })], inventory: [] },
    })
    expect(wrapper.text()).toContain(AGENT_ID)
  })
})
