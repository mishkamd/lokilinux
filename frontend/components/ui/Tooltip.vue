<script setup lang="ts">
import {
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
  TooltipPortal,
  TooltipContent,
} from 'radix-vue'

withDefaults(
  defineProps<{
    text: string
    side?: 'top' | 'right' | 'bottom' | 'left'
    delayDuration?: number
  }>(),
  { side: 'top', delayDuration: 300 },
)
</script>

<template>
  <TooltipProvider :delay-duration="delayDuration" :skip-delay-duration="150">
    <TooltipRoot>
      <!-- ponytail: radix-vue 1.9 serializes the trigger's data-grace-area-trigger
           valueless on the server but as ="" on the client, so every TooltipTrigger
           logs a benign, DEV-ONLY hydration-mismatch warning (attr renders
           identically; production Vue doesn't warn). Ceiling: fix by migrating
           radix-vue -> reka-ui, which reworked SSR attr serialization. -->
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent
          :side="side"
          :side-offset="6"
          class="z-[60] rounded-[var(--radius-sm)] bg-foreground px-2 py-1 text-xs font-medium text-background shadow-md data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0"
        >
          {{ text }}
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>
