interface PublicSettings {
  branding: { company_name: string; logo_url: string }
  security: { require_2fa: boolean }
}

const DEFAULTS = { company_name: 'LokiLinux', logo_url: '/logo.svg' }

export function useBranding() {
  const api = useApi()

  const { data } = useAsyncData('public-settings', async () => {
    try {
      return await api.get<PublicSettings>('/admin/settings/public')
    } catch {
      return null
    }
  })

  const companyName = computed(() => data.value?.branding?.company_name || DEFAULTS.company_name)
  const logoUrl = computed(() => data.value?.branding?.logo_url || DEFAULTS.logo_url)
  const require2FA = computed(() => data.value?.security?.require_2fa ?? false)
  const logoMaskStyle = computed(() => {
    const url = `url(${logoUrl.value})`
    return `mask-image:${url};mask-size:contain;mask-repeat:no-repeat;mask-position:center;-webkit-mask-image:${url};-webkit-mask-size:contain;-webkit-mask-repeat:no-repeat;-webkit-mask-position:center;`
  })

  return { companyName, logoUrl, logoMaskStyle, require2FA }
}
