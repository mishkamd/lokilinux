<script setup lang="ts">
import { SEVERITY_COLORS, CHECK_SOURCE_COLORS } from '~/utils/complianceColors'
import { RefreshCw } from 'lucide-vue-next'
import type { CheckSource } from '~/stores/compliance'

const store = useComplianceStore()
const { rules, rulesTotal, rulesLoading, rulesNextCursor, ruleFilters } = storeToRefs(store)

onMounted(() => store.fetchRules())

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
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Input v-model="ruleFilters.search" placeholder="Search rule ID, title, CCE/NIST/STIG/CIS…" class="w-64"
               @keyup.enter="store.fetchRules()" />
        <Input v-model="ruleFilters.domain" placeholder="Filter by domain (e.g. sshd)" class="w-48"
               @keyup.enter="store.fetchRules()" />
        <Select v-model="ruleFilters.check_source" :options="['', ...CHECK_SOURCES]" placeholder="Coverage" class="w-44"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" placeholder="Severity"
                class="w-36" @change="store.fetchRules()" />
        <Input v-model="ruleFilters.framework" placeholder="Framework (e.g. cis)" class="w-36"
               @keyup.enter="store.fetchRules()" />
        <Input v-model="ruleFilters.platform" placeholder="Platform (e.g. rocky9)" class="w-36"
               @keyup.enter="store.fetchRules()" />
        <Select v-model="ruleFilters.status" :options="[{ label: 'All', value: '' }, { label: 'Enabled', value: 'enabled' }, { label: 'Disabled', value: 'disabled' }]"
                placeholder="Status" class="w-32" @change="store.fetchRules()" />
        <Button variant="outline" @click="store.fetchRules()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ rulesTotal }} rules</Badge>
    </PageHeader>

    <DataTable :rows="rules" :columns="columns" :loading="rulesLoading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/rules/${row.id}`)">
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

    <div v-if="rulesNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchRules(rulesNextCursor!)">
        Load more
      </Button>
    </div>
  </div>
</template>
