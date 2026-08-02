<script setup lang="ts">
import { RefreshCw, Search } from 'lucide-vue-next'

const store = useCveStore()
const { cves, total, loading, summary, filters } = storeToRefs(store)

onMounted(() => store.fetchCves())

const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red',
  HIGH: 'orange',
  MEDIUM: 'amber',
  LOW: 'green',
  NONE: 'gray',
}

const SEVERITY_TEXT_COLORS: Record<string, string> = {
  red: 'text-destructive',
  orange: 'text-orange-600 dark:text-orange-400',
  amber: 'text-warning',
  green: 'text-success',
}

const columns = [
  { key: 'cve_id', label: 'CVE ID' },
  { key: 'cvss_v3_severity', label: 'Severity' },
  { key: 'cvss_v3_score', label: 'CVSS' },
  { key: 'affected_count', label: 'Servers Affected' },
  { key: 'is_actively_exploited', label: 'Exploited' },
  { key: 'published_date', label: 'Published' },
]

const summaryCards = computed(() => [
  { label: 'Critical', count: summary.value.CRITICAL, color: SEVERITY_COLORS.CRITICAL },
  { label: 'High',     count: summary.value.HIGH,     color: SEVERITY_COLORS.HIGH },
  { label: 'Medium',   count: summary.value.MEDIUM,   color: SEVERITY_COLORS.MEDIUM },
  { label: 'Low',      count: summary.value.LOW,      color: SEVERITY_COLORS.LOW },
])

const selectedCve = ref<(typeof cves.value)[0] | null>(null)
const showCveDetail = computed({
  get: () => !!selectedCve.value,
  set: (v) => { if (!v) selectedCve.value = null },
})
</script>

<template>
  <div>
    <!-- Summary cards -->
    <div class="grid grid-cols-4 gap-3 mb-4">
      <Card
        v-for="card in summaryCards"
        :key="card.label"
        class="cursor-pointer hover:shadow-md transition-shadow"
        @click="filters.severity = card.label.toUpperCase(); store.fetchCves()"
      >
        <div class="text-center">
          <p
            class="text-xl font-bold font-mono"
            :class="SEVERITY_TEXT_COLORS[card.color] ?? 'text-foreground'"
          >{{ card.count }}</p>
          <p class="text-sm text-muted-foreground mt-1">{{ card.label }}</p>
        </div>
      </Card>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-56">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            v-model="filters.search"
            placeholder="Search CVE ID..."
            class="pl-9"
            @keyup.enter="store.fetchCves()"
          />
        </div>
        <Select
          v-model="filters.severity"
          :options="SEVERITIES"
          placeholder="Severity"
          class="w-36"
          @change="store.fetchCves()"
        />
        <Checkbox v-model="filters.exploited_only" label="Actively exploited" @change="store.fetchCves()" />
        <Button variant="outline" @click="store.fetchCves()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <Badge color="gray">{{ total }} CVEs</Badge>
    </div>

    <DataTable :rows="cves" :columns="columns" :loading="loading">
      <template #cve_id-data="{ row }">
        <button class="font-mono text-sm text-primary hover:underline" @click="selectedCve = row as typeof cves.value[0]">
          {{ row.cve_id }}
        </button>
      </template>
      <template #cvss_v3_severity-data="{ row }">
        <Badge
          v-if="row.cvss_v3_severity"
          :color="SEVERITY_COLORS[String(row.cvss_v3_severity)] ?? 'gray'"
          size="xs"
        >{{ row.cvss_v3_severity }}</Badge>
        <span v-else class="text-muted-foreground">—</span>
      </template>
      <template #cvss_v3_score-data="{ row }">{{ row.cvss_v3_score ?? '—' }}</template>
      <template #is_actively_exploited-data="{ row }">
        <Badge v-if="row.is_actively_exploited" color="red" size="xs">Yes</Badge>
        <span v-else class="text-muted-foreground text-sm">No</span>
      </template>
      <template #published_date-data="{ row }">
        <span class="font-mono">{{ row.published_date ? new Date(String(row.published_date)).toLocaleDateString() : '—' }}</span>
      </template>
    </DataTable>

    <!-- CVE Detail Dialog -->
    <Dialog v-model="showCveDetail" :title="String(selectedCve?.cve_id ?? '')">
      <template #body>
        <div v-if="selectedCve" class="space-y-4">
          <div class="flex items-center gap-3 flex-wrap">
            <Badge
              v-if="selectedCve.cvss_v3_severity"
              :color="SEVERITY_COLORS[String(selectedCve.cvss_v3_severity)] ?? 'gray'"
            >{{ selectedCve.cvss_v3_severity }} — {{ selectedCve.cvss_v3_score }}</Badge>
            <Badge v-if="selectedCve.is_zero_day" color="red" variant="solid" size="xs">0-day</Badge>
            <Badge v-if="selectedCve.is_actively_exploited" color="red" size="xs">Actively exploited</Badge>
          </div>
          <p class="text-sm">{{ selectedCve.description || 'No description available.' }}</p>
          <dl class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt class="text-muted-foreground">Published</dt>
              <dd>{{ selectedCve.published_date ? new Date(String(selectedCve.published_date)).toLocaleDateString() : '—' }}</dd>
            </div>
            <div>
              <dt class="text-muted-foreground">Servers Affected</dt>
              <dd>{{ selectedCve.affected_count }}</dd>
            </div>
          </dl>
        </div>
      </template>
    </Dialog>
  </div>
</template>
