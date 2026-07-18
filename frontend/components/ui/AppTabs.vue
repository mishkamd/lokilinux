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
          'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
          active === i
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border',
        ]"
        @click="select(i)"
      >
        {{ item.label }}
      </button>
    </div>
    <div v-for="(item, i) in items" :key="item.slot" v-show="active === i">
      <slot :name="item.slot" />
    </div>
  </div>
</template>
