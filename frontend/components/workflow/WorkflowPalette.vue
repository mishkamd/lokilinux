<script setup lang="ts">
import { Search } from 'lucide-vue-next'
import { CATEGORY_LABEL, NODE_REGISTRY, TONE_BG, type NodeCategory, type NodeDefinition } from '~/utils/workflow/registry'
import type { WorkflowNodeType } from '~/types/workflow'

const emit = defineEmits<{ 'add-node': [WorkflowNodeType] }>()

const CATEGORY_ORDER: NodeCategory[] = ['flow', 'execution', 'linux', 'control', 'validation', 'integration']

// Legacy aliases (validation/wait_for_agent) are real entries in the
// registry — old published workflows still resolve their icon/label
// through nodeDefinition() — but they never appear here. The palette only
// ever offers the 14 current capability-based types (plan Partea III §9).
const ALL_DEFINITIONS = Object.values(NODE_REGISTRY).filter(d => !d.legacy)

const search = ref('')

const groups = computed(() => {
  const q = search.value.trim().toLowerCase()
  return CATEGORY_ORDER.map((category) => {
    const items = ALL_DEFINITIONS
      .filter(d => d.category === category)
      .filter(d => !q || d.label.toLowerCase().includes(q) || d.description.toLowerCase().includes(q))
    return { category, items }
  }).filter(g => g.items.length > 0)
})

function onDragStart(event: DragEvent, type: WorkflowNodeType) {
  event.dataTransfer?.setData('application/loki-workflow-node-type', type)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onActivate(def: NodeDefinition) {
  emit('add-node', def.type)
}
</script>

<template>
  <div class="flex h-full w-56 shrink-0 flex-col overflow-hidden border-r border-border bg-card">
    <div class="shrink-0 p-3 pb-2">
      <p class="label-caps mb-2 text-muted-foreground">Add step</p>
      <div class="relative">
        <Search class="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="search"
          type="text"
          placeholder="Search steps…"
          class="w-full rounded-[var(--radius-sm)] border border-border bg-background py-1.5 pl-7 pr-2 text-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-primary-active"
        >
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
      <div v-if="!groups.length" class="pt-6 text-center text-xs text-muted-foreground">No steps match “{{ search }}”.</div>
      <div v-for="group in groups" :key="group.category" class="mb-4">
        <p class="mb-1.5 text-[11px] font-medium text-muted-foreground">{{ CATEGORY_LABEL[group.category] }}</p>
        <div class="space-y-1">
          <button
            v-for="def in group.items" :key="def.type"
            type="button"
            draggable="true"
            :title="def.description"
            class="flex w-full cursor-grab items-center gap-2 rounded-[var(--radius-sm)] border border-border/60 px-2 py-1.5 text-left text-xs transition-colors hover:border-primary-active/50 hover:bg-accent focus-visible:border-primary-active focus-visible:outline-none active:cursor-grabbing"
            @dragstart="onDragStart($event, def.type)"
            @click="onActivate(def)"
          >
            <span class="flex size-5 shrink-0 items-center justify-center rounded-md" :class="TONE_BG[def.tone]">
              <component :is="def.icon" class="size-3" />
            </span>
            <span class="min-w-0 flex-1 truncate">{{ def.label }}</span>
            <span v-if="!def.executable" class="shrink-0 rounded-full border border-border/60 px-1.5 py-0.5 text-[9px] font-medium tracking-wide text-muted-foreground">soon</span>
          </button>
        </div>
      </div>
    </div>

    <p class="shrink-0 border-t border-border px-3 py-2 text-[11px] text-muted-foreground">Drag onto the canvas, or click to add.</p>
  </div>
</template>
