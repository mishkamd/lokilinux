<template>
  <div class="flex h-screen bg-background text-foreground overflow-hidden atmosphere">
    <Toaster rich-colors position="top-center" />

    <!-- Skip to content — the sidebar has ~20 links before the page, so a
         keyboard user must not have to tab through all of them on every
         route. Visible only while focused. -->
    <a
      href="#main-content"
      class="focus-ring sr-only focus:not-sr-only fixed left-3 top-3 z-[70] rounded-[var(--radius-sm)] bg-primary px-3 py-2 text-sm text-primary-foreground"
      @click="focusMain"
    >
      Skip to content
    </a>

    <!-- Mobile backdrop -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm lg:hidden"
      @click="closeSidebar"
    />

    <!-- Sidebar -->
    <aside
      id="app-sidebar"
      ref="sidebarEl"
      @keydown="onSidebarKeydown"
      class="fixed lg:static inset-y-0 left-0 z-40 w-[232px] flex-shrink-0 flex flex-col bg-sidebar border-r border-sidebar-border shadow-[4px_0_32px_rgba(16,24,32,0.08)] dark:shadow-[4px_0_32px_rgba(0,0,0,0.35)] transition-transform duration-[var(--duration-slow)] ease-[var(--ease-out-expo)] -translate-x-full lg:translate-x-0"
      :class="{ 'translate-x-0': sidebarOpen, 'lg:hidden': sidebarCollapsed }"
    >
      <!-- Logo -->
      <div class="h-16 flex items-center justify-between gap-2 px-4 border-b border-sidebar-border">
        <NuxtLink to="/" class="group flex items-center gap-2.5 min-w-0 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring" @click="sidebarOpen = false">
          <span
            role="img"
            :aria-label="companyName"
            class="size-8 shrink-0 bg-sidebar-foreground transition-all duration-300 ease-out group-hover:scale-110 group-hover:-rotate-6 group-hover:bg-primary-active"
            :style="logoMaskStyle"
          />
          <span class="text-2xl font-display font-light text-sidebar-foreground tracking-tight mt-1 truncate transition-all duration-300 ease-out group-hover:translate-x-0.5 group-hover:text-primary-active">{{ companyName }}</span>
        </NuxtLink>
        <button
          type="button"
          class="focus-ring shrink-0 inline-flex items-center justify-center size-8 rounded-lg hover:bg-sidebar-accent text-sidebar-foreground/70 lg:hidden"
          aria-label="Close menu"
          @click="sidebarOpen = false"
        >
          <X class="size-4.5" />
        </button>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-3 px-2 space-y-3" aria-label="Main navigation">
        <div v-for="section in navSections" :key="section.title">
            <p v-if="section.title" class="label-caps px-3 pb-1.5">{{ section.title }}</p>
          <ul class="space-y-0.5">
            <li v-for="link in section.links" :key="link.to">
              <!-- Collapsible parent (e.g. "Ansible" under Automation Engine) -->
              <details v-if="link.children" :open="link.children.some((c) => isActive(c.to))">
                <summary
                  class="focus-ring group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors duration-200 cursor-pointer list-none text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                >
                  <span class="flex items-center justify-center size-5 rounded-md shrink-0 text-sidebar-foreground/60 group-hover:text-sidebar-foreground">
                    <component :is="link.icon" class="size-3.5" />
                  </span>
                  {{ link.label }}
                </summary>
                <ul class="space-y-0.5 mt-0.5 pl-4">
                  <li v-for="child in link.children" :key="child.to">
                    <NuxtLink
                      :to="child.to"
                      :aria-current="isActive(child.to) ? 'page' : undefined"
                      class="focus-ring group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors duration-200"
                      :class="isActive(child.to)
                        ? 'bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active'
                        : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'"
                    >
                      <span
                        class="flex items-center justify-center size-5 rounded-md shrink-0 transition-colors"
                        :class="isActive(child.to) ? 'text-primary-active' : 'text-sidebar-foreground/60 group-hover:text-sidebar-foreground'"
                      >
                        <component :is="child.icon" class="size-3.5" />
                      </span>
                      {{ child.label }}
                    </NuxtLink>
                  </li>
                </ul>
              </details>
              <NuxtLink
                v-else
                :to="link.to"
                :aria-current="isActive(link.to) ? 'page' : undefined"
                class="focus-ring group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors duration-200"
                :class="isActive(link.to)
                  ? 'bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'"
              >
                <span
                  class="flex items-center justify-center size-5 rounded-md shrink-0 transition-colors"
                  :class="isActive(link.to) ? 'text-primary-active' : 'text-sidebar-foreground/60 group-hover:text-sidebar-foreground'"
                >
                  <component :is="link.icon" class="size-3.5" />
                </span>
                {{ link.label }}
              </NuxtLink>
            </li>
          </ul>
        </div>

      </nav>

      <!-- User profile card -->
      <div class="p-2 border-t border-sidebar-border">
        <button
          type="button"
          class="focus-ring flex items-center gap-2 w-full rounded-lg hover:bg-sidebar-accent transition-colors text-left p-1.5"
          @click="showUserModal = true"
          :aria-label="`Settings for ${currentUser?.name ?? (currentUser as Record<string, unknown>)?.username ?? 'User'}`"
        >
          <Avatar size="sm" :fallback="userInitial" />
          <span class="flex-1 min-w-0">
            <span class="block text-sm text-sidebar-foreground truncate">
              {{ currentUser?.name ?? (currentUser as Record<string, unknown>)?.username ?? 'User' }}
            </span>
            <span v-if="userRoleLabel" class="block text-label text-sidebar-foreground/60 truncate">{{ userRoleLabel }}</span>
          </span>
          <LogOut class="size-4 text-sidebar-foreground/50 hover:text-sidebar-foreground shrink-0" @click.stop="handleLogout" />
        </button>
      </div>
    </aside>

    <!-- User Settings Modal -->
    <UserSettingsModal v-model="showUserModal" />

    <!-- Help -->
    <Dialog v-model="showHelp" title="Help" size="sm">
      <div class="space-y-3 text-sm">
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Focus search</span>
          <kbd class="text-label font-medium text-muted-foreground border border-border rounded-md px-1.5 py-0.5">⌘K</kbd>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Toggle theme</span>
          <span class="text-xs text-muted-foreground">Sun/moon icon, top right</span>
        </div>
      </div>
    </Dialog>

    <!-- Main content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <div class="sticky top-0 z-20 flex-shrink-0 border-b border-border bg-background/90">
        <header class="h-16 flex items-center gap-2 sm:gap-3 px-3 sm:px-4">
          <button
            type="button"
            class="focus-ring inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors shrink-0 lg:hidden"
            aria-label="Open menu"
            @click="openSidebar"
          >
            <Menu class="size-4.5" />
          </button>
          <button
            type="button"
            class="focus-ring hidden lg:inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors shrink-0"
            :aria-label="sidebarCollapsed ? 'Show menu' : 'Hide menu'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <PanelLeft v-if="sidebarCollapsed" class="size-4.5" />
            <PanelLeftClose v-else class="size-4.5" />
          </button>

          <h1 class="page-title truncate shrink-0">{{ currentPageTitle }}</h1>

          <div class="hidden lg:flex items-center gap-1.5 shrink-0">
            <NuxtLink
              v-if="criticalAlerts > 0"
              to="/alerts"
              class="focus-ring inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive"
            >
              {{ criticalAlerts }} Critical
            </NuxtLink>
          </div>

          <div class="flex-1 hidden md:flex justify-center">
            <button
              type="button"
              class="focus-ring relative flex w-full max-w-md items-center gap-2.5 h-8 rounded-lg bg-card border border-border pl-3 pr-12 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              aria-label="Open command palette"
              @click="palette.show()"
            >
              <Search class="size-4 shrink-0" />
              <span class="truncate">Search hosts, CVEs, jobs — or jump to a page</span>
              <kbd class="absolute right-3 top-1/2 -translate-y-1/2 text-label font-medium text-muted-foreground border border-border rounded-md px-1.5 py-0.5">⌘K</kbd>
            </button>
          </div>
          <div class="flex-1 md:hidden" />

          <div class="flex items-center gap-1 sm:gap-1.5 shrink-0">
            <slot name="topbar-actions" />
            <button
              type="button"
              class="focus-ring inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors md:hidden"
              aria-label="Open command palette"
              @click="palette.show()"
            >
              <Search class="size-4.5" />
            </button>
            <NuxtLink
              to="/alerts"
              class="focus-ring relative inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              aria-label="Alerts"
            >
              <Bell class="size-4.5" />
              <span
                v-if="activeAlerts > 0"
                class="absolute top-1.5 right-1.5 flex size-4 items-center justify-center rounded-full bg-destructive text-micro font-medium text-destructive-foreground"
              >
                {{ activeAlerts > 9 ? '9+' : activeAlerts }}
              </span>
            </NuxtLink>
            <button
              type="button"
              class="focus-ring inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              aria-label="Help"
              @click="showHelp = true"
            >
              <CircleHelp class="size-4.5" />
            </button>
            <ColorModeButton />
            <button
              type="button"
              class="focus-ring inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors ml-1"
              aria-label="User menu"
              @click="showUserModal = true"
            >
              <Avatar size="sm">
                <UserCircle class="size-5" />
              </Avatar>
            </button>
          </div>
        </header>

      </div>
      <CommandPalette />
      <main id="main-content" tabindex="-1" class="focus:outline-none flex-1 overflow-y-auto p-3 sm:p-4">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  Bell, UserCircle, LogOut, Search, Menu, X,
  PanelLeft, PanelLeftClose, CircleHelp,
} from 'lucide-vue-next'
import { Toaster } from 'vue-sonner'
import { buildNavSections, AREA_TABS, type NavSection } from '~/utils/nav'

const route = useRoute()
const { user: currentUser, isAdmin } = useCurrentUser()
const { signOut } = useAuth()
const { companyName, logoMaskStyle } = useBranding()
const dashboard = useDashboardStore()
const palette = useCommandPalette()
const showUserModal = ref(false)
const showHelp = ref(false)

onMounted(() => dashboard.ensureSummary())

const criticalAlerts = computed(() => dashboard.summary?.alerts.by_severity.CRITICAL ?? 0)
const activeAlerts = computed(() => dashboard.summary?.alerts.active_total ?? 0)

const userInitial = computed(() => {
  const name = currentUser.value?.name ?? (currentUser.value as Record<string, unknown> | null)?.username as string | undefined
  return name?.trim()?.charAt(0)?.toUpperCase() || '?'
})
const userRoleLabel = computed(() => {
  const role = (currentUser.value as Record<string, unknown> | null)?.role as string | undefined
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : ''
})
const sidebarOpen = ref(false)
const sidebarEl = ref<HTMLElement | null>(null)
const sidebarToggleEl = ref<HTMLElement | null>(null)

// The skip link moves the scroll, but the focus has to move with it.
function focusMain() {
  nextTick(() => document.getElementById('main-content')?.focus())
}

// The mobile drawer is a modal surface: Tab stays inside it, Escape closes
// it, and the focus goes back to the button that opened it.
function onSidebarKeydown(e: KeyboardEvent) {
  if (!sidebarOpen.value) return
  if (e.key === 'Escape') {
    e.preventDefault()
    closeSidebar()
    return
  }
  if (e.key !== 'Tab' || !sidebarEl.value) return
  const focusables = Array.from(
    sidebarEl.value.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.offsetParent !== null)
  if (!focusables.length) return
  const first = focusables[0]!
  const last = focusables[focusables.length - 1]!
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

function openSidebar() {
  sidebarOpen.value = true
  sidebarToggleEl.value = document.activeElement as HTMLElement
  nextTick(() => sidebarEl.value?.querySelector<HTMLElement>('a[href], button')?.focus())
}

function closeSidebar() {
  sidebarOpen.value = false
  sidebarToggleEl.value?.focus()
}
const sidebarCollapsed = useLocalStorage('sidebar-collapsed', false)

watch(() => route.path, () => { sidebarOpen.value = false })

async function handleLogout() {
  await signOut()
  await clearNuxtData('current-user')
  await navigateTo('/auth/login')
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    palette.show()
  }
}
onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))

// Ansible plugin gate: nav item only shown once the "ansible-automation"
// Plugin row is is_enabled, matching install/activate/deactivate from /plugins.
const ansibleEnabled = ref(false)
onMounted(async () => {
  const pluginsStore = usePluginsStore()
  await pluginsStore.fetchPlugins()
  ansibleEnabled.value = pluginsStore.plugins.some(
    (p) => p.name === 'ansible-automation' && p.is_enabled,
  )
})

const navSections = computed((): NavSection[] =>
  buildNavSections({ isAdmin: isAdmin.value, ansibleEnabled: ansibleEnabled.value }),
)

function isActive(to: string): boolean {
  // Exact match for index-style links that are themselves a path-prefix of a
  // sibling nav entry (e.g. "/compliance" vs "/compliance/baselines") —
  // otherwise both would show active at once, same reasoning as "/".
  if (to === '/' || to === '/compliance' || to === '/vulnerabilities') return route.path === to
  return route.path.startsWith(to)
}

// A route segment that is an identifier, not a word: /servers/<uuid>,
// /vulnerabilities/CVE-2024-1234, /compliance/standards/<key>/<version>.
function isIdSegment(seg: string): boolean {
  return /^[0-9a-f]{8}-/i.test(seg) || /^(CVE-)/i.test(seg) || /^\d/.test(seg)
}

function humanize(seg: string): string {
  return seg.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

const currentPageTitle = computed((): string => {
  // Tabbed areas name their own pages: /compliance/findings is "Findings",
  // /vulnerabilities/list is "CVE Catalog".
  const areaTab = AREA_TABS.find((t) => t.to === route.path)
  if (areaTab) return areaTab.label
  // navSections already includes the admin-gated Administration section.
  // Children come before their group so a group's own route (e.g. the
  // "Compliance" group pointing at /compliance) can't shadow the more
  // specific child that actually matched.
  const allLinks = navSections.value.flatMap((s) => s.links.flatMap((l) => [...(l.children ?? []), l]))
  // Prefix match (not the sidebar's exact-match rule): the title wants the
  // area a nested child belongs to. Longest match wins, so /compliance/findings
  // never titles as the "/compliance" group.
  const match = allLinks
    .filter((l) => l.to === '/' ? route.path === '/' : route.path === l.to || route.path.startsWith(l.to + '/'))
    .sort((a, b) => b.to.length - a.to.length)[0]
  if (!match) return companyName.value
  // One level below the matched entry the segment names the page
  // ("/compliance/findings" -> "Findings"); an id segment doesn't, so the
  // area's own label stays.
  const segments = route.path.split('/').filter(Boolean)
  const matchedSegments = match.to.split('/').filter(Boolean).length
  if (segments.length > matchedSegments) {
    const seg = segments.at(-1) ?? ''
    if (seg && !isIdSegment(seg)) return humanize(seg)
  }
  return match.label
})

// Drives the browser tab (via nuxt.config.ts's titleTemplate), reusing the
// same label already shown in the page header — one source of truth.
useHead({ title: currentPageTitle })
</script>
