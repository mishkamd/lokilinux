<script setup lang="ts">
import { Sun, Moon } from 'lucide-vue-next'

const colorMode = useColorMode({
  attribute: 'class',
  storageKey: 'lokilinux-color-mode',
  initialValue: 'dark',
  modes: { dark: 'dark', light: 'light' },
})

const isDark = computed(() => colorMode.value === 'dark')

function toggle() {
  colorMode.value = isDark.value ? 'light' : 'dark'
}
</script>

<template>
  <button
    type="button"
    class="inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
    :aria-label="isDark ? 'Light mode' : 'Dark mode'"
    @click="toggle"
  >
    <Sun v-if="isDark" class="size-4" />
    <Moon v-else class="size-4" />
  </button>
</template>
