<script setup lang="ts">
interface TabItem {
  label: string
  slot: string
}

const props = defineProps<{ items: TabItem[] }>()
const emit = defineEmits<{ change: [number] }>()

const active = ref(0)

function select(i: number) {
  active.value = i
  emit('change', i)
}
</script>

<template>
  <div>
    <div class="flex border-b border-border gap-1">
      <button
        v-for="(item, i) in items"
        :key="item.slot"
        type="button"
        :class="[
          'relative px-4 py-2.5 text-sm font-medium transition-colors duration-[var(--duration-fast)]',
          active === i
            ? 'text-foreground'
            : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="select(i)"
      >
        {{ item.label }}
        <span
          v-if="active === i"
          class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary animate-in fade-in slide-in-from-bottom-1 duration-[var(--duration-normal)]"
        />
      </button>
    </div>
    <div v-for="(item, i) in items" :key="item.slot" v-show="active === i">
      <slot :name="item.slot" />
    </div>
  </div>
</template>
