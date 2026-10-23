import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import MultiSelect from './MultiSelect.vue'

const options = [
  { label: 'web-01', value: 'a' },
  { label: 'web-02', value: 'b' },
  { label: 'db-01', value: 'c' },
]

// The popup is portalled to the body, so pick the most recent one.
function lastListbox() {
  const all = Array.from(document.querySelectorAll('[role="listbox"]'))
  return all.at(-1) as HTMLElement | undefined
}

describe('ui/MultiSelect', () => {
  it('renders the field with the Input token recipe and a chip per selected value', async () => {
    const wrapper = await mountSuspended(MultiSelect, {
      props: { modelValue: ['a'], options, placeholder: 'Select servers…' },
    })

    const field = wrapper.find('input').element.closest('div')!
    expect(field.className).toContain('rounded-[var(--radius-sm)]')
    expect(field.className).toContain('border-input')

    expect(wrapper.text()).toContain('web-01')
    expect(wrapper.text()).not.toContain('web-02')
  }, 20000)

  it('opens a Select-identical popup and drives it with the keyboard', async () => {
    const wrapper = await mountSuspended(MultiSelect, {
      props: { modelValue: [], options },
    })

    const input = wrapper.find('input')
    await input.trigger('focus')
    await wrapper.vm.$nextTick()

    const listbox = lastListbox()
    expect(listbox).toBeDefined()
    expect(listbox!.className).toContain('bg-popover')
    expect(listbox!.className).toContain('shadow-[var(--shadow-overlay)]')

    const rows = Array.from(listbox!.querySelectorAll('[role="option"]'))
    expect(rows).toHaveLength(3)
    expect(rows[0]!.className).toContain('data-[highlighted]:bg-accent')
    expect(rows[0]!.hasAttribute('data-highlighted')).toBe(true)

    // Arrow down moves the highlight, Enter picks the highlighted row.
    await input.trigger('keydown', { key: 'ArrowDown' })
    await wrapper.vm.$nextTick()
    expect(rows[1]!.hasAttribute('data-highlighted')).toBe(true)

    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')![0]![0]).toEqual(['b'])
  }, 20000)

  it('filters the list as you type', async () => {
    const wrapper = await mountSuspended(MultiSelect, {
      props: { modelValue: [], options },
    })

    const input = wrapper.find('input')
    await input.trigger('focus')
    await input.setValue('db')
    await wrapper.vm.$nextTick()

    const rows = Array.from(lastListbox()!.querySelectorAll('[role="option"]'))
    const visible = rows.filter((el) => (el as HTMLElement).style.display !== 'none')
    expect(visible.map((el) => el.textContent!.trim())).toEqual(['db-01'])
  }, 20000)

  it('closes the popup on Escape', async () => {
    const wrapper = await mountSuspended(MultiSelect, {
      props: { modelValue: [], options },
    })

    const input = wrapper.find('input')
    await input.trigger('focus')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent({ name: 'ComboboxRoot' }).props('open')).toBe(true)

    // radix listens for Escape on the window, not on the input.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.findComponent({ name: 'ComboboxRoot' }).props('open')).toBe(false)
  }, 20000)
})
