<script setup lang="ts">
import type { NuxtError } from '#app'
import { Home } from 'lucide-vue-next'

defineProps<{ error: NuxtError }>()

const { companyName, logoMaskStyle } = useBranding()

function goHome() {
  clearError({ redirect: '/' })
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center px-4 atmosphere">
    <div class="text-center">
      <div class="flex justify-center mb-6">
        <span class="flex items-center justify-center size-14 rounded-2xl bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)]">
          <span
            role="img"
            :aria-label="companyName"
            class="size-7 shrink-0 bg-primary-active"
            :style="logoMaskStyle"
          />
        </span>
      </div>
      <p class="label-caps text-muted-foreground">{{ error.statusCode }}</p>
      <h1 class="text-3xl font-display font-light text-foreground tracking-tight mt-2">
        {{ error.statusCode === 404 ? 'Page not found' : 'Something went wrong' }}
      </h1>
      <p v-if="error.statusMessage" class="text-sm text-muted-foreground mt-2">{{ error.statusMessage }}</p>
      <p class="text-xs text-muted-foreground mt-6">{{ companyName }} — Secure. Automate. Operate.</p>
      <Button class="mt-8" @click="goHome">
        <Home class="size-4" />
        Back to Overview
      </Button>
    </div>
  </div>
</template>
