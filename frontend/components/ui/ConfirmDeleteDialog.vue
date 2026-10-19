<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue?: boolean
    title?: string
    /** Name of the entity being deleted, shown in bold inside the default message */
    entityName?: string
    /** Overrides the default "Delete X? This cannot be undone." body */
    description?: string
    loading?: boolean
    confirmLabel?: string
  }>(),
  { title: 'Confirm delete', confirmLabel: 'Delete' },
)

const emit = defineEmits<{
  'update:modelValue': [boolean]
  confirm: []
}>()

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <Dialog :model-value="modelValue" size="sm" :title="title" @update:model-value="emit('update:modelValue', $event)">
    <template #body>
      <slot name="description">
        <p class="text-sm text-muted-foreground">
          Delete <strong class="text-foreground">{{ entityName }}</strong>? This cannot be undone.
        </p>
      </slot>
      <slot />
    </template>
    <template #footer>
      <Button variant="ghost" @click="close">Cancel</Button>
      <Button variant="destructive" :loading="loading" @click="emit('confirm')">{{ confirmLabel }}</Button>
    </template>
  </Dialog>
</template>
