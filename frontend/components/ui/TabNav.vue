<script setup lang="ts">
interface TabDef {
  label: string
  to: string
}

/**
 * Link-based tab bar for nested routes. Real URLs (not client state) so every
 * tab is shareable, bookmarkable and middle-clickable.
 */
const props = defineProps<{ tabs: TabDef[] }>()
const route = useRoute()

const active = computed(() => props.tabs.find((t) => t.to === route.path)?.to)
</script>

<template>
  <nav class="mb-4 flex gap-1 overflow-x-auto border-b border-border" role="tablist">
    <NuxtLink
      v-for="tab in tabs"
      :key="tab.to"
      :to="tab.to"
      role="tab"
      :aria-selected="active === tab.to"
      :class="[
        'focus-ring relative shrink-0 px-4 py-2.5 text-sm font-medium transition-colors duration-[var(--duration-fast)]',
        active === tab.to
          ? 'text-foreground'
          : 'text-muted-foreground hover:text-foreground',
      ]"
    >
      {{ tab.label }}
      <span
        v-if="active === tab.to"
        class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary"
      />
    </NuxtLink>
  </nav>
</template>
