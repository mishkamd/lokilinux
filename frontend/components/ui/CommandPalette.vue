<script setup lang="ts">
import {
  Search, CornerDownLeft, Server as ServerIcon, ShieldAlert, ClipboardList, Siren,
  Moon, Sun, RefreshCw, Zap, LayoutDashboard, type LucideIcon,
} from 'lucide-vue-next'
import { buildNavSections, navDestinations } from '~/utils/nav'
import { fuzzyScore } from '~/utils/fuzzy'

interface Item {
  key: string
  label: string
  hint?: string
  group: string
  icon: unknown
  to?: string
  run?: () => void
}

const { open, hide } = useCommandPalette()
const { isAdmin } = useCurrentUser()
const pluginsStore = usePluginsStore()
const serversStore = useServersStore()
const vulnsStore = useVulnerabilitiesStore()
const jobsStore = useJobsStore()
const incidentsStore = useIncidentsStore()

const colorMode = useColorMode({
  attribute: 'class',
  storageKey: 'lokilinux-color-mode',
  initialValue: 'dark',
  modes: { dark: 'dark', light: 'light' },
})

const query = ref('')
const selected = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)
const entitiesLoaded = ref(false)

let restoreFocusTo: HTMLElement | null = null

watch(open, async (v) => {
  if (v) {
    restoreFocusTo = (document.activeElement as HTMLElement) ?? null
    query.value = ''
    selected.value = 0
    await nextTick()
    inputEl.value?.focus()
  } else {
    // Hand focus back to whatever opened the palette.
    restoreFocusTo?.focus()
    restoreFocusTo = null
  }
})

// ── sources ────────────────────────────────────────────────────────────────
const navSections = computed(() =>
  buildNavSections({
    isAdmin: isAdmin.value,
    ansibleEnabled: pluginsStore.plugins.some((p) => p.name === 'ansible-automation' && p.is_enabled),
  }),
)

const navItems = computed<Item[]>(() =>
  navDestinations(navSections.value).map((l) => ({
    key: `nav:${l.to}`,
    label: l.label,
    group: 'Go to',
    icon: l.icon,
    to: l.to,
  })),
)

const actionItems = computed<Item[]>(() => [
  {
    key: 'action:assessment',
    label: 'Run compliance assessment',
    hint: 'Compliance',
    group: 'Actions',
    icon: Zap,
    to: '/compliance?action=assessment',
  },
  {
    key: 'action:policy-set',
    label: 'Create policy set',
    hint: 'Compliance',
    group: 'Actions',
    icon: Zap,
    to: '/compliance/policies?action=new',
  },
  {
    key: 'action:refresh',
    label: 'Refresh data',
    hint: 'current view',
    group: 'Actions',
    icon: RefreshCw,
    run: () => refreshNuxtData(),
  },
  {
    key: 'action:theme',
    label: colorMode.value === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
    group: 'Actions',
    icon: colorMode.value === 'dark' ? Sun : Moon,
    run: () => {
      colorMode.value = colorMode.value === 'dark' ? 'light' : 'dark'
    },
  },
])

const entityItems = computed<Item[]>(() => [
  ...serversStore.servers.map((s) => ({
    key: `server:${s.id}`,
    label: s.hostname || s.id,
    hint: [s.os_name, s.os_version].filter(Boolean).join(' ') || s.id,
    group: 'Servers',
    icon: ServerIcon,
    to: `/servers/${s.id}`,
  })),
  ...vulnsStore.cves.map((c) => ({
    key: `cve:${c.cve_id}`,
    label: c.cve_id,
    hint: c.cvss_v3_severity || `${c.affected_count} affected`,
    group: 'CVEs',
    icon: ShieldAlert,
    to: `/vulnerabilities/${c.cve_id}`,
  })),
  ...jobsStore.jobs.map((j) => ({
    key: `job:${j.id}`,
    label: j.name || j.id,
    hint: j.status,
    group: 'Jobs',
    icon: ClipboardList,
    to: `/jobs?search=${encodeURIComponent(j.name || j.id)}`,
  })),
  ...incidentsStore.incidents.map((i) => ({
    key: `incident:${i.id}`,
    label: i.title || i.id,
    hint: i.severity,
    group: 'Incidents',
    icon: Siren,
    to: `/incidents/${i.id}`,
  })),
])

/** Entities are only fetched once the user actually types something. */
async function ensureEntities() {
  if (entitiesLoaded.value) return
  entitiesLoaded.value = true
  await Promise.allSettled([
    serversStore.fetchServers(),
    vulnsStore.fetchCves(),
    jobsStore.fetchJobs(),
    incidentsStore.fetchIncidents(),
  ])
}

const results = computed<Item[]>(() => {
  const q = query.value.trim()
  if (!q) {
    // Empty query: navigation + actions, no entity fetch.
    return [...actionItems.value, ...navItems.value]
  }
  const all = [...actionItems.value, ...navItems.value, ...entityItems.value]
  return all
    .map((item) => {
      const score = Math.min(
        ...[item.label, item.hint ?? '', item.group]
          .map((field) => fuzzyScore(q, field))
          .filter((s): s is number => s !== null),
      )
      return { item, score: Number.isFinite(score) ? score : null }
    })
    .filter((r): r is { item: Item; score: number } => r.score !== null)
    .sort((a, b) => a.score - b.score)
    .slice(0, 20)
    .map((r) => r.item)
})

watch(query, () => {
  selected.value = 0
  if (query.value.trim().length >= 2) ensureEntities()
})

const grouped = computed(() => {
  const groups: { name: string; items: Item[] }[] = []
  for (const item of results.value) {
    const g = groups.find((x) => x.name === item.group)
    if (g) g.items.push(item)
    else groups.push({ name: item.group, items: [item] })
  }
  return groups
})

const flat = computed(() => grouped.value.flatMap((g) => g.items))

function move(delta: number) {
  if (!flat.value.length) return
  selected.value = (selected.value + delta + flat.value.length) % flat.value.length
  nextTick(() => {
    listEl.value?.querySelector('[data-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  })
}

async function run(item: Item) {
  hide()
  if (item.run) {
    item.run()
    return
  }
  if (item.to) await navigateTo(item.to)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = flat.value[selected.value]
    if (item) run(item)
  } else if (e.key === 'Tab') {
    // The palette is driven with ↑↓/↵; Tab would escape into the page
    // behind it, which is not inert.
    e.preventDefault()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    hide()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm"
      @click="hide"
      @keydown="onKeydown"
    >
      <div
        class="surface-dialog mx-auto mt-[10vh] flex max-h-[70vh] w-[min(40rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-[var(--radius-xl)] shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        @click.stop
      >
        <div class="flex items-center gap-2 border-b border-border px-4">
          <Search class="size-4 shrink-0 text-muted-foreground" />
          <input
            ref="inputEl"
            v-model="query"
            type="text"
            placeholder="Search hosts, CVEs, jobs, incidents — or jump to a page"
            class="focus-ring h-12 w-full rounded-md bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-palette-list"
            autocomplete="off"
            spellcheck="false"
          >
          <kbd class="hidden shrink-0 rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground sm:block">esc</kbd>
        </div>

        <div ref="listEl" id="command-palette-list" class="min-h-0 flex-1 overflow-y-auto py-1" role="listbox">
          <p v-if="!results.length" class="px-4 py-6 text-center text-sm text-muted-foreground">
            Nothing matches “{{ query }}”.
          </p>
          <div v-for="group in grouped" :key="group.name">
            <p class="label-caps px-4 pb-1 pt-2 text-muted-foreground">{{ group.name }}</p>
            <button
              v-for="item in group.items"
              :key="item.key"
              type="button"
              role="option"
              :aria-selected="flat[selected]?.key === item.key"
              :data-selected="flat[selected]?.key === item.key"
              class="focus-ring flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors"
              :class="flat[selected]?.key === item.key ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/60'"
              @mouseenter="selected = flat.findIndex((x) => x.key === item.key)"
              @click="run(item)"
            >
              <component :is="item.icon" class="size-4 shrink-0 opacity-80" />
              <span class="min-w-0 flex-1 truncate text-foreground">{{ item.label }}</span>
              <span v-if="item.hint" class="shrink-0 truncate text-xs text-muted-foreground">{{ item.hint }}</span>
              <CornerDownLeft v-if="flat[selected]?.key === item.key" class="size-3.5 shrink-0 opacity-60" />
            </button>
          </div>
        </div>

        <div class="flex items-center gap-4 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
