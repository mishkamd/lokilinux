<script setup lang="ts">
defineProps<{
  label?: string
  name?: string
  help?: string
  required?: boolean
}>()
</script>

<template>
  <!-- The control lives inside the <label>, so the visible label is
       associated with it implicitly — no id/`for` plumbing at the call site
       (which almost never passed a matching id, leaving screen readers with
       an unlabelled field). -->
  <div class="space-y-1.5">
    <label class="block space-y-1.5">
      <span v-if="label" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
        {{ label }}<span v-if="required" class="text-destructive ml-0.5">*</span>
      </span>
      <slot />
    </label>
    <!-- Outside the label: the help text must not end up in the field's
         accessible name. -->
    <p v-if="help" class="text-xs font-normal text-muted-foreground">{{ help }}</p>
  </div>
</template>
