<script setup lang="ts">
// useStepper comes from @vueuse/core, auto-imported via the @vueuse/nuxt
// module — no wizard/stepper primitive existed anywhere in the app before
// this, so this is a thin presentational shell (progress header) around it
// rather than a from-scratch state machine.
const props = defineProps<{ steps: string[] }>()

const stepper = useStepper(props.steps)

defineExpose({ stepper })
</script>

<template>
  <div>
    <ol class="flex items-center mb-6">
      <li v-for="(s, i) in props.steps" :key="s" class="flex flex-1 items-center last:flex-none">
        <button
          type="button"
          class="flex shrink-0 items-center gap-2 disabled:cursor-not-allowed"
          :disabled="i > stepper.index.value"
          @click="i < stepper.index.value && stepper.goTo(s)"
        >
          <span
            class="flex size-6 shrink-0 items-center justify-center rounded-full text-[12px] font-medium transition-colors"
            :class="i < stepper.index.value
              ? 'bg-primary-active text-primary-foreground'
              : i === stepper.index.value
                ? 'border-2 border-primary-active text-primary-active'
                : 'border border-border text-muted-foreground'"
          >{{ i + 1 }}</span>
          <span
            class="whitespace-nowrap text-[13px]"
            :class="i === stepper.index.value ? 'font-medium' : 'text-muted-foreground'"
          >{{ s }}</span>
        </button>
        <div v-if="i < props.steps.length - 1" class="mx-3 h-px flex-1 bg-border" />
      </li>
    </ol>

    <slot :stepper="stepper" />
  </div>
</template>
