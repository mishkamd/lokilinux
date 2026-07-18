<script setup lang="ts">
defineProps<{
  label?: string
  name?: string
  help?: string
  required?: boolean
}>()
</script>

<template>
  <div class="space-y-1.5">
    <Label v-if="label" :for="name">
      {{ label }}<span v-if="required" class="text-destructive ml-0.5">*</span>
    </Label>
    <slot />
    <p v-if="help" class="text-xs text-muted-foreground">{{ help }}</p>
  </div>
</template>
