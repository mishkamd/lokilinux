import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import DataTable from './DataTable.vue'

const columns = [
  { key: 'name', label: 'Name' },
  // The actions column: empty label, not sortable.
  { key: 'actions', label: '', noSort: true },
]

describe('ui/DataTable header', () => {
  it('renders an empty header cell without stray text nodes', async () => {
    // A bare `{{ col.label }}` interpolation made the server emit a text
    // node where the client expected a fragment — Vue reported
    // "Hydration completed but contains mismatches" on every table that has
    // an action column. The label goes through an element (or nothing).
    const wrapper = await mountSuspended(DataTable, {
      props: { rows: [{ id: 'a', name: 'row' }], columns },
    })
    const actionsHeader = wrapper.findAll('th').at(-1)!
    expect(actionsHeader.text()).toBe('')
    expect(actionsHeader.element.childNodes.length).toBeLessThanOrEqual(2)
  })

  it('keeps the label of a sortable column', async () => {
    const wrapper = await mountSuspended(DataTable, {
      props: { rows: [{ id: 'a', name: 'row' }], columns, sortable: true },
    })
    expect(wrapper.findAll('th')[0]!.text()).toContain('Name')
  })

  it('keeps the label of a non-sortable column', async () => {
    const wrapper = await mountSuspended(DataTable, {
      props: {
        rows: [{ id: 'a', name: 'row' }],
        columns: [{ key: 'name', label: 'Name' }],
      },
    })
    expect(wrapper.findAll('th')[0]!.text()).toContain('Name')
  })
})
