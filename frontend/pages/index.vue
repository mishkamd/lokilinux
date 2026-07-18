<script setup lang="ts">
import { Server, ShieldAlert, ClipboardList, BellDot, FileText, Puzzle } from 'lucide-vue-next'

const api = useApi()
const { hasRole } = useCurrentUser()

interface DashboardSummary {
  agents: {
    total: number
    by_status: Record<string, number>
    active: number
    updates_available: number
    os_distribution: Record<string, number>
  }
  vulnerabilities: { unresolved_total: number; by_severity: Record<string, number> }
  jobs: { total: number; by_status: Record<string, number>; running: number }
  alerts: { active_total: number; by_severity: Record<string, number> }
  policies: { total: number; enabled: number }
  plugins: { total: number; enabled: number }
}

const summary = ref<DashboardSummary | null>(null)
const loadError = ref(false)

async function load() {
  try {
    summary.value = await api.get<DashboardSummary>('/dashboard/summary')
  } catch {
    loadError.value = true
  }
}
onMounted(load)

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'gray', LOW: 'gray', INFO: 'gray',
}

const severityBadges = (bySeverity: Record<string, number>) =>
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    .filter(sev => (bySeverity[sev] ?? 0) > 0)
    .map(sev => ({ label: `${sev}: ${bySeverity[sev]}`, color: SEVERITY_COLOR[sev] }))

const statusBadges = (byStatus: Record<string, number>) =>
  Object.entries(byStatus).filter(([, count]) => count > 0).map(([status, count]) => ({ label: `${status}: ${count}` }))
</script>

<template>
  <div class="relative -m-3 sm:-m-4 min-h-full p-3 sm:p-4 glass-backdrop">
    <div v-if="loadError" class="text-sm text-red-500">Nu s-au putut încărca datele dashboard-ului.</div>

    <div v-else-if="!summary" class="space-y-3">
      <div class="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        <Skeleton v-for="i in 6" :key="i" class="h-24 rounded-xl" />
      </div>
      <Skeleton class="h-36 rounded-xl" />
    </div>

    <div v-else class="space-y-3">
      <!-- Row 1: stat cards — one unified grid, no orphaned/uneven rows -->
      <div class="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 [&>*]:animate-in [&>*]:fade-in-0 [&>*]:slide-in-from-bottom-2 [&>*]:duration-[250ms] [&>*]:fill-mode-backwards">
        <StatCard
          style="animation-delay: 0ms"
          :icon="Server" label="Servere" :to="'/servers'"
          :value="summary.agents.total" :subtitle="`${summary.agents.active} active`"
          :badges="statusBadges(summary.agents.by_status)"
        />
        <StatCard
          style="animation-delay: 30ms"
          :icon="ShieldAlert" label="Vulnerabilități" :to="'/vulnerabilities'"
          :value="summary.vulnerabilities.unresolved_total"
          :badges="severityBadges(summary.vulnerabilities.by_severity)"
          empty-badges-text="fără vulnerabilități deschise"
        />
        <StatCard
          style="animation-delay: 60ms"
          :icon="ClipboardList" label="Joburi" :to="'/jobs'"
          :value="summary.jobs.total" :subtitle="`${summary.jobs.running} în execuție`"
          :badges="statusBadges(summary.jobs.by_status)"
        />
        <StatCard
          style="animation-delay: 90ms"
          :icon="BellDot" label="Alerte" :to="'/alerts'"
          :value="summary.alerts.active_total"
          :badges="severityBadges(summary.alerts.by_severity)"
          empty-badges-text="fără alerte active"
        />
        <StatCard style="animation-delay: 120ms" :icon="FileText" label="Politici" to="/policies" :value="summary.policies.total" :subtitle="`${summary.policies.enabled} active`" />
        <StatCard style="animation-delay: 150ms" :icon="Puzzle" label="Plugin-uri" to="/plugins" :value="summary.plugins.total" :subtitle="`${summary.plugins.enabled} activate`" />
      </div>

      <!-- Row 2: OS distribution + top vulnerabilities -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 [&>*]:animate-in [&>*]:fade-in-0 [&>*]:slide-in-from-bottom-2 [&>*]:duration-[250ms] [&>*]:fill-mode-backwards">
        <OsDistributionDonut style="animation-delay: 180ms" class="col-span-2" :distribution="summary.agents.os_distribution" />
        <SeverityBarList style="animation-delay: 210ms" class="col-span-2" :by-severity="summary.vulnerabilities.by_severity" />
      </div>

      <!-- Row 3: activity + agent status -->
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-3 [&>*]:animate-in [&>*]:fade-in-0 [&>*]:slide-in-from-bottom-2 [&>*]:duration-[250ms] [&>*]:fill-mode-backwards">
        <RecentActivityFeed v-if="hasRole('AUDITOR')" style="animation-delay: 240ms" />
        <div
          class="glass-card rounded-xl p-3 flex items-center justify-between h-fit"
          style="animation-delay: 270ms"
          :class="{ 'xl:col-span-2': !hasRole('AUDITOR') }"
        >
          <div class="flex items-center gap-2">
            <span
              class="size-2 rounded-full"
              :class="summary.agents.active === summary.agents.total ? 'bg-success' : 'bg-warning'"
            />
            <span class="label-caps">Stare agenți</span>
          </div>
          <span class="text-[12px] text-muted-foreground tabular-nums">{{ summary.agents.active }} / {{ summary.agents.total }} conectați</span>
        </div>
      </div>
    </div>
  </div>
</template>
