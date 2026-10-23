<script setup lang="ts">
import { SEVERITY_COLORS, CHECK_SOURCE_COLORS, RULE_STATUS_COLORS } from '~/utils/complianceColors'
import { RefreshCw } from 'lucide-vue-next'
import type { CheckSource, RuleStatus } from '~/stores/compliance'

const store = useComplianceStore()
const { rules, rulesTotal, rulesLoading, rulesNextCursor, ruleFilters, ruleFacets } = storeToRefs(store)

onMounted(async () => {
  await Promise.all([store.fetchRules(), store.fetchRuleFacets()])
})

const CHECK_SOURCES: CheckSource[] = ['CEL', 'OVAL_UNMAPPED', 'OSCAP_FALLBACK']
const RULE_STATUSES: RuleStatus[] = ['ACTIVE', 'DISABLED', 'REFERENCE_ONLY', 'DEPRECATED']

// The filter values come from the catalog itself (GET /compliance/rules/facets),
// so an operator picks a domain instead of guessing its spelling.
const domainOptions = computed(() => [
  { label: 'All domains', value: '' },
  ...ruleFacets.value.domains.map((d) => ({ label: `${d.value} (${d.count})`, value: d.value })),
])
const frameworkOptions = computed(() => [
  { label: 'All frameworks', value: '' },
  ...ruleFacets.value.frameworks.map((f) => ({ label: `${f.value} (${f.count})`, value: f.value })),
])
const platformOptions = computed(() => [
  { label: 'All platforms', value: '' },
  ...ruleFacets.value.platforms.map((p) => ({ label: `${p.value} (${p.count})`, value: p.value })),
])

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
               aria-label="Search rules" @keyup.enter="store.fetchRules()" />
        <Select v-model="ruleFilters.domain" :options="domainOptions" placeholder="All domains" class="w-44"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.check_source" :options="['', ...CHECK_SOURCES]" placeholder="Coverage" class="w-44"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" placeholder="Severity"
                class="w-36" @change="store.fetchRules()" />
        <Select v-model="ruleFilters.framework" :options="frameworkOptions" placeholder="All frameworks" class="w-44"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.platform" :options="platformOptions" placeholder="All platforms" class="w-40"
                @change="store.fetchRules()" />
        <Select v-model="ruleFilters.status" :options="[{ label: 'All', value: '' }, { label: 'Enabled', value: 'enabled' }, { label: 'Disabled', value: 'disabled' }]"
                 placeholder="Status" class="w-32" @change="store.fetchRules()" />
        <Select v-model="ruleFilters.rule_status" :options="['', ...RULE_STATUSES]"
                 placeholder="Lifecycle" class="w-36" @change="store.fetchRules()" />
        <Button variant="outline" @click="store.fetchRules()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ rulesTotal }} rules</Badge>
    </PageHeader>

    <DataTable
      :rows="rules"
      :columns="columns"
      :loading="rulesLoading"
      sortable
      :page-size="25"
      empty-title="No rules found"
      rows-clickable
      @row-click="(row) => navigateTo(`/compliance/rules/${row.id}`)"
     caption="Compliance rules" preferences-key="compliance-rules">
      <template #title-data="{ row }">
        <div>
          <div class="flex items-center gap-2">
            <p class="font-medium">{{ row.title }}</p>
            <Badge v-if="row.status !== 'ACTIVE'" :color="RULE_STATUS_COLORS[row.status] ?? 'gray'" size="xs">
              {{ row.status }}
            </Badge>
          </div>
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
