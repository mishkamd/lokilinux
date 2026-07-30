<template>
  <div class="flex h-screen bg-background text-foreground overflow-hidden">
    <Toaster rich-colors position="top-center" />

    <!-- Mobile backdrop -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-30 bg-black/60 lg:hidden"
      @click="sidebarOpen = false"
    />

    <!-- Sidebar -->
    <aside
      class="fixed lg:static inset-y-0 left-0 z-40 w-[232px] flex-shrink-0 flex flex-col bg-sidebar/95 backdrop-blur-xl border-r border-sidebar-border shadow-[4px_0_24px_rgba(0,0,0,0.25)] transition-transform duration-200 -translate-x-full lg:translate-x-0"
      :class="{ 'translate-x-0': sidebarOpen, 'lg:hidden': sidebarCollapsed }"
    >
      <!-- Logo -->
      <div class="relative h-16 flex items-center justify-start px-4 border-b border-sidebar-border">
        <NuxtLink to="/" class="group flex items-center gap-2.5" @click="sidebarOpen = false">
          <span
            role="img"
            :aria-label="companyName"
            class="size-8 shrink-0 bg-sidebar-foreground transition-all duration-300 ease-out group-hover:scale-110 group-hover:-rotate-6 group-hover:bg-primary-active"
            :style="logoMaskStyle"
          />
          <span class="text-2xl font-display font-semibold text-sidebar-foreground tracking-tight mt-1.5 transition-all duration-300 ease-out group-hover:translate-x-0.5 group-hover:text-primary-active">{{ companyName }}</span>
        </NuxtLink>
        <button
          type="button"
          class="absolute right-4 top-1/2 -translate-y-1/2 inline-flex items-center justify-center size-8 rounded-lg hover:bg-white/[0.05] text-sidebar-foreground/70 lg:hidden"
          aria-label="Close menu"
          @click="sidebarOpen = false"
        >
          <X class="size-4.5" />
        </button>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-3 px-2 space-y-3" aria-label="Main navigation">
        <div v-for="section in navSections" :key="section.title">
          <p class="label-caps px-3 pb-1.5">{{ section.title }}</p>
          <ul class="space-y-0.5">
            <li v-for="link in section.links" :key="link.to">
              <!-- Collapsible parent (e.g. "Ansible" under Automation Engine) -->
              <details v-if="link.children" :open="link.children.some((c) => isActive(c.to))">
                <summary
                  class="group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[14px] font-medium transition-colors duration-200 cursor-pointer list-none text-sidebar-foreground/70 hover:bg-white/[0.05] hover:text-sidebar-foreground"
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
                      class="group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[14px] font-medium transition-colors duration-200"
                      :class="isActive(child.to)
                        ? 'bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active'
                        : 'text-sidebar-foreground/70 hover:bg-white/[0.05] hover:text-sidebar-foreground'"
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
                class="group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[14px] font-medium transition-colors duration-200"
                :class="isActive(link.to)
                  ? 'bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active'
                  : 'text-sidebar-foreground/70 hover:bg-white/[0.05] hover:text-sidebar-foreground'"
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

        <div v-if="isAdmin">
          <p class="label-caps px-3 pb-1.5">Administration</p>
          <ul class="space-y-0.5">
            <li v-for="link in adminLinks" :key="link.to">
              <NuxtLink
                :to="link.to"
                :aria-current="isActive(link.to) ? 'page' : undefined"
                class="group relative flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[14px] font-medium transition-colors duration-200"
                :class="isActive(link.to)
                  ? 'bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active'
                  : 'text-sidebar-foreground/70 hover:bg-white/[0.05] hover:text-sidebar-foreground'"
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
          class="flex items-center gap-2 w-full rounded-lg hover:bg-sidebar-accent transition-colors text-left p-1.5"
          @click="showUserModal = true"
          :aria-label="`Settings for ${currentUser?.name ?? (currentUser as Record<string, unknown>)?.username ?? 'User'}`"
        >
          <Avatar size="sm">
            <UserCircle class="size-5" />
          </Avatar>
          <span class="text-[14px] text-sidebar-foreground truncate flex-1 min-w-0">
            {{ currentUser?.name ?? (currentUser as Record<string, unknown>)?.username ?? 'User' }}
          </span>
          <LogOut class="size-4 text-sidebar-foreground/50 hover:text-sidebar-foreground shrink-0" @click.stop="handleLogout" />
        </button>
      </div>
    </aside>

    <!-- User Settings Modal -->
    <UserSettingsModal v-model="showUserModal" />

    <!-- Main content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <div class="sticky top-0 z-20 flex-shrink-0 border-b border-border bg-background/80 backdrop-blur-xl">
        <header class="h-16 flex items-center gap-2 sm:gap-3 px-3 sm:px-4">
          <button
            type="button"
            class="inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors shrink-0 lg:hidden"
            aria-label="Open menu"
            @click="sidebarOpen = true"
          >
            <Menu class="size-4.5" />
          </button>
          <button
            type="button"
            class="hidden lg:inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors shrink-0"
            :aria-label="sidebarCollapsed ? 'Show menu' : 'Hide menu'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <PanelLeft v-if="sidebarCollapsed" class="size-4.5" />
            <PanelLeftClose v-else class="size-4.5" />
          </button>

          <h1 class="text-sm font-semibold truncate shrink-0">{{ currentPageTitle }}</h1>

          <div class="flex-1 hidden md:flex justify-center">
            <div class="relative w-full max-w-md">
              <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <input
                ref="searchInput"
                v-model="searchQuery"
                type="text"
                placeholder="Search servers, jobs, CVEs..."
                class="w-full h-8 rounded-lg bg-card border border-border pl-10 pr-14 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-primary transition-colors"
                @keyup.enter="onSearchEnter"
              >
              <kbd class="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-medium text-muted-foreground border border-border rounded-md px-1.5 py-0.5">⌘K</kbd>
            </div>
          </div>
          <div class="flex-1 md:hidden" />

          <div class="flex items-center gap-1 sm:gap-1.5 shrink-0">
            <slot name="topbar-actions" />
            <button
              type="button"
              class="inline-flex items-center justify-center size-9 rounded-xl hover:bg-accent transition-colors md:hidden"
              aria-label="Search"
              @click="mobileSearchOpen = !mobileSearchOpen"
            >
              <Search class="size-4.5" />
            </button>
            <NuxtLink
              to="/alerts"
              class="inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              aria-label="Alerts"
            >
              <Bell class="size-4.5" />
            </NuxtLink>
            <ColorModeButton />
            <button
              type="button"
              class="inline-flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors ml-1"
              aria-label="User menu"
              @click="showUserModal = true"
            >
              <Avatar size="sm">
                <UserCircle class="size-5" />
              </Avatar>
            </button>
          </div>
        </header>

        <div v-if="mobileSearchOpen" class="px-4 pb-3 md:hidden">
          <div class="relative w-full">
            <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <input
              v-model="searchQuery"
              type="text"
              placeholder="Search servers, jobs, CVEs..."
              class="w-full h-11 rounded-[16px] bg-card border border-border pl-10 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-primary transition-colors"
              autofocus
              @keyup.enter="onSearchEnter"
            >
          </div>
        </div>
      </div>
      <main class="flex-1 overflow-y-auto p-3 sm:p-4">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  LayoutDashboard, Server, Cpu, ClipboardList, ShieldAlert,
  FileText, Puzzle, BellDot, Bell, Users, Settings, UserCircle, LogOut, Search, Menu, X,
  PanelLeft, PanelLeftClose, Bot, Layers, FolderKanban, ShieldCheck,
  BookCheck, ListChecks, GitCompare, Wrench, FileSearch, FileChartColumn,
} from 'lucide-vue-next'
import { Toaster } from 'vue-sonner'

interface NavLink {
  to: string
  label: string
  icon: unknown
  children?: NavLink[]
}

const route = useRoute()
const { user: currentUser, isAdmin } = useCurrentUser()
const { signOut } = useAuth()
const { companyName, logoMaskStyle } = useBranding()
const showUserModal = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const sidebarOpen = ref(false)
const sidebarCollapsed = useLocalStorage('sidebar-collapsed', false)
const mobileSearchOpen = ref(false)

watch(() => route.path, () => { sidebarOpen.value = false })

async function handleLogout() {
  await signOut()
  await navigateTo('/auth/login')
}

function onSearchEnter() {
  if (!searchQuery.value.trim()) return
  navigateTo({ path: '/servers', query: { search: searchQuery.value.trim() } })
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    searchInput.value?.focus()
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

const navSections = computed((): { title: string; links: NavLink[] }[] => [
  {
    title: 'Infrastructure',
    links: [
      { to: '/',                label: 'Dashboard',       icon: LayoutDashboard },
      { to: '/servers',         label: 'Servers',         icon: Server },
      { to: '/agents',          label: 'Agents',          icon: Cpu },
      { to: '/jobs',            label: 'Jobs',            icon: ClipboardList },
      { to: '/vulnerabilities', label: 'Vulnerabilities', icon: ShieldAlert },
    ],
  },
  {
    title: 'Automation Engine',
    links: [
      { to: '/policies', label: 'Policies', icon: FileText },
      { to: '/plugins',  label: 'Plugins',  icon: Puzzle },
      ...(ansibleEnabled.value ? [{
        to: '/automation/ansible/playbooks', label: 'Ansible', icon: Bot,
        children: [
          { to: '/automation/ansible/projects',  label: 'Projects',      icon: FolderKanban },
          { to: '/automation/ansible/playbooks', label: 'Playbooks',     icon: FileText },
          { to: '/automation/ansible/roles',     label: 'Roles',         icon: Layers },
          { to: '/automation/ansible/templates', label: 'Job Templates', icon: ClipboardList },
        ],
      }] : []),
    ],
  },
  {
    title: 'Compliance',
    links: [
      { to: '/compliance', label: 'Overview', icon: ShieldCheck },
      { to: '/compliance/baselines', label: 'Baselines', icon: FileText },
      { to: '/compliance/policies', label: 'Policy Sets', icon: BookCheck },
      { to: '/compliance/rules', label: 'Rule Catalog', icon: ListChecks },
      { to: '/compliance/drift', label: 'Drift', icon: GitCompare },
      { to: '/compliance/file-integrity', label: 'File Integrity', icon: FileSearch },
      { to: '/compliance/remediation', label: 'Remediation', icon: Wrench },
      { to: '/compliance/reports', label: 'Reports', icon: FileChartColumn },
    ],
  },
  {
    title: 'Observability',
    links: [
      { to: '/alerts', label: 'Alerts', icon: BellDot },
    ],
  },
])

const adminLinks: NavLink[] = [
  { to: '/admin/users',    label: 'Users',     icon: Users },
  { to: '/admin/audit',    label: 'Audit Log', icon: ClipboardList },
  { to: '/admin/settings', label: 'Settings',  icon: Settings },
]

function isActive(to: string): boolean {
  // Exact match for index-style links that are themselves a path-prefix of a
  // sibling nav entry (e.g. "/compliance" vs "/compliance/baselines") —
  // otherwise both would show active at once, same reasoning as "/".
  if (to === '/' || to === '/compliance') return route.path === to
  return route.path.startsWith(to)
}

const currentPageTitle = computed((): string => {
  const allLinks = navSections.value.flatMap((s) => s.links.flatMap((l) => [l, ...(l.children ?? [])]))
  const match = allLinks.find((l) => isActive(l.to))
    ?? adminLinks.find((l) => isActive(l.to))
  return match?.label ?? companyName.value
})
</script>
