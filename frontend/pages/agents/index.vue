<script setup lang="ts">
import { Server, Download, Key, Clipboard, ChevronUp, Settings } from 'lucide-vue-next'
import { buildPackageCards, type PackagesResponse, type PkgLink } from '~/utils/agentPackages'

const api = useApi()
const toast = useToast()
const { canEdit, isAdmin } = useCurrentUser()

const packages = ref<PackagesResponse | null>(null)
const packagesError = ref(false)

async function loadPackages() {
  try {
    packages.value = await api.get<PackagesResponse>('/agent/packages')
  } catch {
    packagesError.value = true
  }
}
onMounted(loadPackages)

const packageCards = computed(() => buildPackageCards(packages.value))

const downloading = ref<string | null>(null)

async function downloadDirect(link: PkgLink) {
  downloading.value = `${link.os}-${link.arch}`
  try {
    const blob = await api.get<Blob>(
      `/agent/download-direct?os=${encodeURIComponent(link.os)}&arch=${link.arch}`,
      { responseType: 'blob' },
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = link.filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast.add({ title: 'Download started', description: link.filename, color: 'green' })
  } catch {
    toast.add({ title: 'Download error', color: 'red' })
  } finally {
    downloading.value = null
  }
}

interface AgentConfig { download_base: string; version: string; platform_url: string }
const cfg = ref<AgentConfig>({ download_base: '', version: '0.1.0', platform_url: '' })
const cfgPending = ref(false)
const showConfig = ref(false)

onMounted(async () => {
  if (!isAdmin.value) return
  try { cfg.value = await api.get<AgentConfig>('/admin/agent-config') } catch {}
})

function isHttpUrl(v: string): boolean {
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

function validateConfig(): string | null {
  if (!isHttpUrl(cfg.value.platform_url)) return 'Server URL must be a valid http(s) URL'
  if (cfg.value.download_base && !isHttpUrl(cfg.value.download_base))
    return 'Download Base must be a valid http(s) URL'
  return null
}

async function saveConfig() {
  const err = validateConfig()
  if (err) {
    toast.add({ title: 'Invalid configuration', description: err, color: 'red' })
    return
  }
  cfgPending.value = true
  try {
    await api.put('/admin/agent-config', cfg.value)
    toast.add({ title: 'Configuration saved', color: 'green' })
    showConfig.value = false
    await loadPackages()
  } catch {
    toast.add({ title: 'Save error', color: 'red' })
  } finally {
    cfgPending.value = false
  }
}

const tokenLabel = ref('')
interface EnrollResult { token: string; install_command: string; url_source?: 'db' | 'env' }
const enrollResult = ref<EnrollResult | null>(null)
const tokenPending = ref(false)

async function generateToken() {
  tokenPending.value = true
  enrollResult.value = null
  try {
    const res = await api.post<EnrollResult>('/agent/enrollment-token', { label: tokenLabel.value })
    // url_source=db → admin set Server URL explicitly in Configure URLs — trust it.
    // Otherwise the backend only knows its env default (often localhost); the live
    // browser origin is guaranteed reachable from wherever this session works, and
    // /api/v1/** is same-origin-proxied, so build the command from that instead.
    if (res.url_source === 'db') {
      enrollResult.value = res
    } else {
      const origin = window.location.origin
      enrollResult.value = {
        ...res,
        install_command: `curl -fsSL ${origin}/api/v1/agent/install.sh | bash -s -- --token=${res.token} --url=${origin}`,
      }
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    toast.add({ title: 'Error', description: err?.message, color: 'red' })
  } finally {
    tokenPending.value = false
  }
}

async function copy(text: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      // navigator.clipboard requires HTTPS/localhost — fall back to the
      // legacy execCommand path for plain-HTTP LAN deployments.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    toast.add({ title: 'Copied!', color: 'green' })
  } catch {
    toast.add({ title: 'Copy error', description: 'Copy the text manually.', color: 'red' })
  }
}
</script>

<template>
  <div class="space-y-8">
    <!-- Platform URL bar -->
    <div v-if="packages?.platform_url" class="flex items-center gap-3 p-3 rounded-lg bg-muted text-sm">
      <Server class="size-4 text-muted-foreground shrink-0" />
      <span class="text-muted-foreground">Server URL:</span>
      <code class="font-mono font-medium flex-1">{{ packages.platform_url }}</code>
      <Button size="xs" variant="ghost" aria-label="Copy server URL" @click="copy(packages!.platform_url)">
        <Clipboard class="size-4" />
      </Button>
    </div>

    <!-- Admin config -->
    <div v-if="isAdmin">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold">Agent packages</h2>
        <Button size="sm" variant="outline" @click="showConfig = !showConfig">
          <component :is="showConfig ? ChevronUp : Settings" class="size-4" />
          Configure URLs
        </Button>
      </div>
      <Card v-if="showConfig" class="mb-4">
        <div class="space-y-4">
          <FormField label="Server URL (platform)" name="platform_url">
            <Input v-model="cfg.platform_url" placeholder="http://lokilinux.example.com:8000" />
          </FormField>
          <FormField label="Download Base URL" name="download_base">
            <Input v-model="cfg.download_base" placeholder="https://github.com/lokilinux/releases/download/v0.1.0" />
          </FormField>
          <FormField label="Agent version" name="version">
            <Input v-model="cfg.version" placeholder="0.1.0" class="max-w-xs" />
          </FormField>
          <div class="flex gap-2">
            <Button :loading="cfgPending" @click="saveConfig">Save</Button>
            <Button variant="ghost" @click="showConfig = false">Cancel</Button>
          </div>
        </div>
      </Card>
    </div>
    <div v-else>
      <h2 class="text-lg font-semibold mb-3">Agent packages</h2>
    </div>

    <!-- Download cards -->
    <div v-if="packagesError" class="text-sm text-destructive">Failed to load package URLs.</div>
    <div v-else-if="!packages" class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Skeleton v-for="i in 3" :key="i" class="h-36 rounded-lg" />
    </div>
    <div v-else class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card v-for="card in packageCards" :key="card.type">
        <template #header>
          <div class="flex items-center gap-2">
            <Download class="size-5 text-primary" />
            <span class="font-semibold">{{ card.type }}</span>
            <Badge size="xs">v{{ packages.version }}</Badge>
          </div>
          <p class="text-xs text-muted-foreground mt-1">{{ card.description }}</p>
        </template>
        <div class="space-y-2">
          <template v-for="link in card.links" :key="link.arch">
            <!-- Generated directly by platform (local build) -->
            <Button
              v-if="link.available"
              :loading="downloading === `${link.os}-${link.arch}`"
              variant="default"
              size="sm"
              class="w-full"
              @click="downloadDirect(link)"
            >
              <Download class="size-4" />
              {{ link.label }}
            </Button>
            <!-- Fallback: configured external URL -->
            <Button v-else-if="link.external" :to="link.external" target="_blank" variant="outline" size="sm" class="w-full">
              <Download class="size-4" />
              {{ link.label }} (external)
            </Button>
            <Button v-else disabled variant="secondary" size="sm" class="w-full">
              {{ link.label }} — unavailable
            </Button>
          </template>
        </div>
      </Card>
    </div>

    <!-- Enrollment token -->
    <section v-if="canEdit">
      <h2 class="text-lg font-semibold mb-1">Install agent on new server</h2>
      <p class="text-sm text-muted-foreground mb-4">Token valid 24h · single-use · run command on target server as root</p>

      <Card class="max-w-2xl">
        <div class="space-y-4">
          <div class="flex gap-3 items-end">
            <FormField label="Label (optional)" name="label" class="flex-1">
              <Input v-model="tokenLabel" placeholder="e.g. prod-web-01" :disabled="tokenPending" />
            </FormField>
            <Button :loading="tokenPending" @click="generateToken">
              <Key class="size-4" />
              Generate token
            </Button>
          </div>

          <div v-if="enrollResult" class="space-y-3">
            <Alert color="green" title="Token generated — valid 24h" />

            <FormField label="Token">
              <div class="flex gap-2">
                <Input :model-value="enrollResult.token" readonly class="font-mono text-xs flex-1" />
                <Button variant="outline" aria-label="Copy token" @click="copy(enrollResult.token)">
                  <Clipboard class="size-4" />
                </Button>
              </div>
            </FormField>

            <FormField label="Install command (run as root on target server)">
              <div class="flex gap-2">
                <Input :model-value="enrollResult.install_command" readonly class="font-mono text-xs flex-1" />
                <Button variant="outline" aria-label="Copy install command" @click="copy(enrollResult.install_command)">
                  <Clipboard class="size-4" />
                </Button>
              </div>
            </FormField>

            <Button variant="ghost" size="sm" @click="enrollResult = null; tokenLabel = ''">
              Generate another token
            </Button>
          </div>
        </div>
      </Card>
    </section>
  </div>
</template>
