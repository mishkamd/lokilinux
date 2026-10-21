<script setup lang="ts">
import { useId } from 'vue'

defineProps<{
  label?: string
  name?: string
  help?: string
  required?: boolean
  /** Validation message. Rendered under the control and linked to it with
   *  aria-describedby; the control gets aria-invalid from the slot props. */
  error?: string
}>()

// The message's id — the control points at it with aria-describedby.
const messageId = useId()
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
      <slot :invalid="!!error" :described-by="error ? messageId : undefined" />
    </label>
    <!-- Outside the label: the help text must not end up in the field's
         accessible name. -->
    <p v-if="error" :id="messageId" class="text-xs font-normal text-destructive">{{ error }}</p>
    <p v-else-if="help" class="text-xs font-normal text-muted-foreground">{{ help }}</p>
  </div>
</template>
