<script setup lang="ts">
import { ShieldAlert } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  bySeverity: Record<string, number>
  title?: string
}>(), {
  title: 'Top vulnerabilități',
})

const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const
const SEVERITY_BAR_COLOR: Record<string, string> = {
  CRITICAL: 'bg-destructive', HIGH: 'bg-orange-500', MEDIUM: 'bg-warning', LOW: 'bg-info',
}
const SEVERITY_LABEL: Record<string, string> = {
  CRITICAL: 'Critice', HIGH: 'Înalte', MEDIUM: 'Medii', LOW: 'Scăzute',
}

const rows = computed(() => {
  const max = Math.max(1, ...SEVERITY_ORDER.map(sev => props.bySeverity[sev] ?? 0))
  return SEVERITY_ORDER.map(sev => ({
    sev,
    count: props.bySeverity[sev] ?? 0,
    pct: Math.round(((props.bySeverity[sev] ?? 0) / max) * 100),
  }))
})

const total = computed(() => SEVERITY_ORDER.reduce((sum, sev) => sum + (props.bySeverity[sev] ?? 0), 0))
</script>

<template>
  <div class="glass-card rounded-xl p-3">
    <div class="flex items-center gap-1.5 text-muted-foreground mb-2.5">
      <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
        <ShieldAlert class="size-3" />
      </span>
      <h2 class="label-caps">{{ props.title }}</h2>
    </div>
    <div v-if="total === 0" class="text-xs text-muted-foreground py-2 text-center">Nicio vulnerabilitate deschisă.</div>
    <div v-else class="space-y-1.5">
      <div v-for="row in rows" :key="row.sev" class="flex items-center gap-2 text-xs">
        <span class="w-12 shrink-0 text-muted-foreground">{{ SEVERITY_LABEL[row.sev] }}</span>
        <div class="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
          <div class="h-full rounded-full transition-all" :class="SEVERITY_BAR_COLOR[row.sev]" :style="{ width: `${row.pct}%` }" />
        </div>
        <span class="w-5 text-right font-medium tabular-nums">{{ row.count }}</span>
      </div>
    </div>
  </div>
</template>
