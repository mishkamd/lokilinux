<script setup lang="ts">
/**
 * Button + hidden native file input, wired together. Extracted from two
 * identical hand-rolled copies (Ansible playbooks upload, Ansible role
 * folder upload) — everything else about file handling (reading content,
 * building the create/update payload) stays with the caller.
 */
const props = withDefaults(defineProps<{
  accept?: string
  multiple?: boolean
  /** Lets the user pick a whole folder (maps to webkitdirectory + directory). */
  directory?: boolean
  loading?: boolean
  disabled?: boolean
  variant?: 'default' | 'outline' | 'secondary' | 'ghost'
}>(), {
  variant: 'outline',
})

const emit = defineEmits<{ change: [files: FileList] }>()

const input = ref<HTMLInputElement | null>(null)

function onChange(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (files?.length) emit('change', files)
  if (input.value) input.value.value = ''
}
</script>

<template>
  <div class="inline-block">
    <input
      ref="input"
      type="file"
      :accept="props.accept"
      :multiple="props.multiple"
      :webkitdirectory="props.directory ? '' : undefined"
      :directory="props.directory ? '' : undefined"
      class="hidden"
      @change="onChange"
    />
    <Button :variant="props.variant" :loading="props.loading" :disabled="props.disabled" @click="input?.click()">
      <slot />
    </Button>
  </div>
</template>
