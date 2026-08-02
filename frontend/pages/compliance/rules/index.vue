<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import type { CheckSource } from '~/stores/compliance'

const store = useComplianceStore()
const { rules, rulesTotal, rulesLoading, ruleFilters } = storeToRefs(store)

onMounted(() => store.fetchRules())

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}
const CHECK_SOURCE_COLORS: Record<CheckSource, string> = {
  CEL: 'green', OVAL_UNMAPPED: 'gray', OSCAP_FALLBACK: 'amber',
}
const CHECK_SOURCES: CheckSource[] = ['CEL', 'OVAL_UNMAPPED', 'OSCAP_FALLBACK']

const columns = [
  { key: 'title', label: 'Rule' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'check_source', label: 'Coverage' },
  { key: 'source_version', label: 'Source' },
]
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Input v-model="ruleFilters.domain" placeholder="Filter by domain (e.g. sshd)" class="w-56"
               @keyup.enter="store.fetchRules()" />
        <Select v-model="ruleFilters.check_source" :options="['', ...CHECK_SOURCES]" placeholder="Coverage" class="w-44"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" placeholder="Severity"
                class="w-36" @change="store.fetchRules()" />
        <Button variant="outline" @click="store.fetchRules()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ rulesTotal }} rules</Badge>
    </div>

    <DataTable :rows="rules" :columns="columns" :loading="rulesLoading">
      <template #title-data="{ row }">
        <div>
          <p class="font-medium">{{ row.title }}</p>
          <p class="text-xs text-muted-foreground font-mono">{{ row.rule_key }}</p>
        </div>
      </template>
      <template #domain-data="{ row }">
        <Badge color="gray" size="xs">{{ row.domain }}</Badge>
      </template>
      <template #severity-data="{ row }">
        <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #check_source-data="{ row }">
        <Badge :color="CHECK_SOURCE_COLORS[row.check_source as CheckSource] ?? 'gray'" size="xs">{{ row.check_source }}</Badge>
      </template>
      <template #source_version-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.source_version || '—' }}</span>
      </template>
    </DataTable>
  </div>
</template>
