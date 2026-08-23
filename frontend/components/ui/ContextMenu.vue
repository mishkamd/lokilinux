<script setup lang="ts">
import type { Component } from 'vue'

// A right-click target here (a Vue Flow node/edge/pane) isn't a DOM element
// we control — it's rendered through Vue Flow's own slot system, so
// wrapping every target in radix-vue's ContextMenuTrigger (gesture-driven,
// expects to own the element it wraps) would mean fighting two libraries
// over the same right-click. Vue Flow already emits node-context-menu/
// edge-context-menu/pane-context-menu with exactly the data needed, so
// this is a plain "open programmatically at (x,y)" popover instead —
// still radix-vue's design vocabulary (DESIGN.md tokens, same overlay
// shadow tier as Sheet.vue/Dialog.vue) without adding a dependency.
export interface ContextMenuItem {
  label: string
  icon?: Component
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
}
export type ContextMenuEntry = ContextMenuItem | { separator: true }

const open = ref(false)
const x = ref(0)
const y = ref(0)
const entries = ref<ContextMenuEntry[]>([])

function show(event: MouseEvent, menuEntries: ContextMenuEntry[]) {
  event.preventDefault()
  x.value = event.clientX
  y.value = event.clientY
  entries.value = menuEntries
  open.value = true
}
function hide() {
  open.value = false
}
function select(entry: ContextMenuItem) {
  if (entry.disabled) return
  hide()
  entry.onSelect()
}

useEventListener(window, 'click', hide)
useEventListener(window, 'blur', hide)
useEventListener(window, 'scroll', hide, true)
useEventListener(window, 'keydown', (e: KeyboardEvent) => { if (e.key === 'Escape') hide() })

defineExpose({ show, hide })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed z-50 min-w-[190px] overflow-hidden rounded-[var(--radius-md)] border border-border bg-card p-1 shadow-[var(--shadow-overlay)]"
      :style="{ left: `${x}px`, top: `${y}px` }"
      role="menu"
      @click.stop
      @contextmenu.prevent
    >
      <template v-for="(entry, i) in entries" :key="i">
        <div v-if="'separator' in entry" class="my-1 h-px bg-border" />
        <button
          v-else type="button" role="menuitem"
          class="flex w-full cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-xs outline-none transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
          :class="entry.danger ? 'text-destructive hover:bg-destructive/10' : ''"
          :disabled="entry.disabled"
          @click="select(entry)"
        >
          <component :is="entry.icon" v-if="entry.icon" class="size-3.5 shrink-0" />
          <span class="truncate">{{ entry.label }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>
