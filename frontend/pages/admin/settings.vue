<script setup lang="ts">
definePageMeta({ layout: 'default' })

interface AllSettings {
  agent: { platform_url: string; version: string; download_base: string }
  security: {
    ldap_enabled: boolean; ldap_host: string; ldap_port: number; ldap_bind_dn: string
    ldap_bind_password: string; ldap_search_base: string; ldap_use_ssl: boolean
    require_2fa: boolean; session_expiry_days: number; session_update_age_hours: number
    password_min_length: number; rate_limit_enabled: boolean; rate_limit_per_minute: number
    audit_log_retention_days: number
  }
  notifications: {
    smtp_host: string; smtp_port: number; smtp_user: string; smtp_password: string
    smtp_from: string; slack_webhook_url: string
  }
  fleet: { heartbeat_timeout_minutes: number; job_stale_timeout_minutes: number }
  retention: { metrics_days: number }
  cve: { feed_source_url: string; sync_interval_hours: number }
  branding: { company_name: string; logo_url: string }
  plugins: { marketplace_url: string }
  repo: { default_mirror_url: string }
}

const api = useApi()
const toast = useToast()

const form = reactive<AllSettings>({
  agent: { platform_url: '', version: '0.1.0', download_base: '' },
  security: {
    ldap_enabled: false, ldap_host: '', ldap_port: 389, ldap_bind_dn: '',
    ldap_bind_password: '', ldap_search_base: '', ldap_use_ssl: false,
    require_2fa: false, session_expiry_days: 7, session_update_age_hours: 24,
    password_min_length: 8, rate_limit_enabled: true, rate_limit_per_minute: 120,
    audit_log_retention_days: 365,
  },
  notifications: { smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '', smtp_from: '', slack_webhook_url: '' },
  fleet: { heartbeat_timeout_minutes: 5, job_stale_timeout_minutes: 60 },
  retention: { metrics_days: 365 },
  cve: { feed_source_url: '', sync_interval_hours: 24 },
  branding: { company_name: 'LokiLinux', logo_url: '/logo.svg' },
  plugins: { marketplace_url: '' },
  repo: { default_mirror_url: '' },
})

const saving = reactive<Record<string, boolean>>({})

const { pending } = await useAsyncData('platform-settings', async () => {
  const cfg = await api.get<AllSettings>('/admin/settings')
  Object.assign(form.agent, cfg.agent)
  Object.assign(form.security, cfg.security)
  Object.assign(form.notifications, cfg.notifications)
  Object.assign(form.fleet, cfg.fleet)
  Object.assign(form.retention, cfg.retention)
  Object.assign(form.cve, cfg.cve)
  Object.assign(form.branding, cfg.branding)
  Object.assign(form.plugins, cfg.plugins)
  Object.assign(form.repo, cfg.repo)
  return cfg
})

async function saveGroup(group: keyof AllSettings) {
  saving[group] = true
  try {
    await api.put('/admin/settings', { [group]: form[group] })
    toast.add({ title: 'Settings saved', color: 'green' })
  } catch {
    toast.add({ title: 'Save failed', color: 'red' })
  } finally {
    saving[group] = false
  }
}

async function saveGroups(...groups: (keyof AllSettings)[]) {
  for (const g of groups) saving[g] = true
  try {
    await api.put('/admin/settings', Object.fromEntries(groups.map((g) => [g, form[g]])))
    toast.add({ title: 'Settings saved', color: 'green' })
  } catch {
    toast.add({ title: 'Save failed', color: 'red' })
  } finally {
    for (const g of groups) saving[g] = false
  }
}
</script>

<template>
  <div class="w-full space-y-8">
    <h2 class="text-lg font-semibold">Platform Settings</h2>

    <div v-if="pending" class="flex justify-center py-8">
      <span class="size-5 animate-spin rounded-full border-2 border-primary border-t-transparent inline-block" />
    </div>

    <div v-else class="space-y-8">
      <!-- Section — Access & Security -->
      <section class="space-y-3">
        <p class="label-caps px-1">Access & Security</p>

        <Card>
          <template #header>LDAP / Active Directory</template>
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <span class="text-sm">Enable LDAP authentication</span>
              <Switch v-model="form.security.ldap_enabled" />
            </div>
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Host">
                <Input v-model="form.security.ldap_host" placeholder="ldap.example.com" />
              </FormField>
              <FormField label="Port">
                <Input v-model.number="form.security.ldap_port" type="number" placeholder="389" />
              </FormField>
              <FormField label="Bind DN">
                <Input v-model="form.security.ldap_bind_dn" placeholder="cn=service,dc=example,dc=com" />
              </FormField>
              <FormField label="Bind Password">
                <Input v-model="form.security.ldap_bind_password" type="password" placeholder="••••••••" />
              </FormField>
              <FormField label="Search Base">
                <Input v-model="form.security.ldap_search_base" placeholder="ou=users,dc=example,dc=com" />
              </FormField>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-sm">Use SSL/TLS</span>
              <Switch v-model="form.security.ldap_use_ssl" />
            </div>
            <p class="text-xs text-muted-foreground">
              Configuration stored — real bind to server not connected yet (needs a real LDAP server for testing).
            </p>
            <div class="flex justify-end gap-2 pt-1">
              <Button variant="outline" disabled title="Requires working LDAP bind">Test connection</Button>
              <Button :loading="saving.security" @click="saveGroup('security')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Authentication & Sessions</template>
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div>
                <span class="text-sm">Require 2FA for all users</span>
                <p class="text-xs text-muted-foreground">Soft enforcement — redirects to TOTP enrollment at login if not enabled.</p>
              </div>
              <Switch v-model="form.security.require_2fa" />
            </div>
            <div class="flex items-center justify-between">
              <span class="text-sm">Rate limiting enabled</span>
              <Switch v-model="form.security.rate_limit_enabled" />
            </div>
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              <FormField label="Session duration (days)">
                <Input v-model.number="form.security.session_expiry_days" type="number" />
              </FormField>
              <FormField label="Rolling refresh (hours)">
                <Input v-model.number="form.security.session_update_age_hours" type="number" />
              </FormField>
              <FormField label="Minimum password length">
                <Input v-model.number="form.security.password_min_length" type="number" />
              </FormField>
              <FormField label="Requests / minute / IP">
                <Input v-model.number="form.security.rate_limit_per_minute" type="number" />
              </FormField>
            </div>
            <p class="text-xs text-muted-foreground">Session and password length require Nuxt backend restart (read at boot).</p>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.security" @click="saveGroup('security')">Save</Button>
            </div>
          </div>
        </Card>
      </section>

      <!-- Section — Platform & Operations -->
      <section class="space-y-3">
        <p class="label-caps px-1">Platform & Operations</p>

        <Card>
          <template #header>Agent Distribution</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Platform URL" help="Base URL of this control plane">
                <Input v-model="form.agent.platform_url" placeholder="https://lokilinux.example.com" />
              </FormField>
              <FormField label="Agent Version">
                <Input v-model="form.agent.version" placeholder="0.1.0" />
              </FormField>
              <FormField label="Download Base URL" help="Override for external agent binary hosting (optional)">
                <Input v-model="form.agent.download_base" placeholder="https://cdn.example.com/releases" />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.agent" @click="saveGroup('agent')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Notifications (SMTP / Slack)</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="SMTP Host">
                <Input v-model="form.notifications.smtp_host" placeholder="smtp.example.com" />
              </FormField>
              <FormField label="SMTP Port">
                <Input v-model.number="form.notifications.smtp_port" type="number" />
              </FormField>
              <FormField label="SMTP User">
                <Input v-model="form.notifications.smtp_user" />
              </FormField>
              <FormField label="SMTP Password">
                <Input v-model="form.notifications.smtp_password" type="password" placeholder="••••••••" />
              </FormField>
              <FormField label="From Address">
                <Input v-model="form.notifications.smtp_from" placeholder="alerts@example.com" />
              </FormField>
              <FormField label="Slack Webhook URL">
                <Input v-model="form.notifications.slack_webhook_url" placeholder="https://hooks.slack.com/services/..." />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.notifications" @click="saveGroup('notifications')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Retention & CVE Feed</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              <FormField label="Audit log retention (days)">
                <Input v-model.number="form.security.audit_log_retention_days" type="number" />
              </FormField>
              <FormField label="Metrics retention (days)" help="Informational only — does not modify TimescaleDB">
                <Input v-model.number="form.retention.metrics_days" type="number" />
              </FormField>
              <FormField label="CVE feed source" help="Reserved — future NVD sync">
                <Input v-model="form.cve.feed_source_url" placeholder="https://services.nvd.nist.gov/rest/json/cves/2.0" />
              </FormField>
              <FormField label="Sync interval (hours)">
                <Input v-model.number="form.cve.sync_interval_hours" type="number" />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.retention" @click="saveGroups('retention', 'cve', 'security')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Fleet Defaults</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Heartbeat timeout (minutes)" help="Agent becomes INACTIVE after this many minutes without heartbeat">
                <Input v-model.number="form.fleet.heartbeat_timeout_minutes" type="number" />
              </FormField>
              <FormField label="Job stale timeout (minutes)" help="Stuck job (QUEUED/RUNNING) marked TIMEOUT after this many minutes">
                <Input v-model.number="form.fleet.job_stale_timeout_minutes" type="number" />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.fleet" @click="saveGroup('fleet')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Branding</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Company name">
                <Input v-model="form.branding.company_name" placeholder="LokiLinux" />
              </FormField>
              <FormField label="Logo URL">
                <Input v-model="form.branding.logo_url" placeholder="/logo.svg" />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.branding" @click="saveGroup('branding')">Save</Button>
            </div>
          </div>
        </Card>

        <Card>
          <template #header>Plugins & Repositories</template>
          <div class="space-y-4">
            <div class="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Plugin marketplace URL" help="Reserved — no discovery yet">
                <Input v-model="form.plugins.marketplace_url" />
              </FormField>
              <FormField label="Default repo mirror" help="Reserved — repositories table does not exist">
                <Input v-model="form.repo.default_mirror_url" />
              </FormField>
            </div>
            <div class="flex justify-end pt-1">
              <Button :loading="saving.plugins" @click="saveGroups('plugins', 'repo')">Save</Button>
            </div>
          </div>
        </Card>
      </section>
    </div>
  </div>
</template>
