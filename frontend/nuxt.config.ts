import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  ssr: true,
  compatibilityDate: '2024-11-01',

  app: {
    head: {
      title: 'LokiLinux',
      // %s comes from each page's useHead({ title }) — layouts/default.vue
      // feeds it the same currentPageTitle already shown in the header, and
      // layouts/auth.vue sets its own for the login screen.
      titleTemplate: '%s · LokiLinux',
      meta: [
        { name: 'color-scheme', content: 'dark light' },
        {
          name: 'description',
          content: 'Enterprise Linux fleet management — patch management, vulnerability scanning, compliance automation, and remediation at scale.',
        },
        // Every route sits behind auth (server/middleware/auth.ts) — there's
        // no public content here for a search engine to rank, and indexing
        // an internal admin tool risks leaking infrastructure details
        // (server counts, CVE dashboards, org names) into search results.
        { name: 'robots', content: 'noindex, nofollow' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }],
      script: [
        {
          // Anti-FOUC: seeds the dark theme before hydration so useColorMode's
          // storageKey lookup finds a value instead of falling through to system pref.
          innerHTML: `(function(){try{var k='lokilinux-color-mode',m=localStorage.getItem(k);if(!m){m='dark';localStorage.setItem(k,m);}document.documentElement.classList.toggle('dark',m==='dark');}catch(e){}})();`,
        },
      ],
    },
  },

  future: {
    compatibilityVersion: 4,
  },

  modules: [
    '@pinia/nuxt',
    '@vueuse/nuxt',
    '@nuxt/fonts',
  ],

  fonts: {
    families: [
      { name: 'Inter', provider: 'google' },
      { name: 'IBM Plex Mono', provider: 'google' },
      { name: 'Bitcount Single', provider: 'google' },
    ],
  },

  components: [
    { path: '~/components/ui', pathPrefix: false },
    { path: '~/components/dashboard', pathPrefix: false },
    '~/components',
  ],

  css: ['~/assets/css/global.css', 'vue-sonner/style.css'],

  vite: {
    plugins: [tailwindcss()],
    server: {
      // Vite dev server rejects unknown Host headers by default. The backend
      // validates Better Auth sessions by calling this container over the
      // internal Docker network (Host: lokilinux-frontend), which gets
      // blocked otherwise — every login redirects straight back to /auth/login.
      allowedHosts: ['lokilinux-frontend'],
    },
  },

  routeRules: {
    // Same-origin proxy: browser hits /api/v1/** on the Nuxt origin, Nitro forwards
    // to the FastAPI container. One public URL fronts frontend + API (no CORS).
    '/api/v1/**': {
      proxy: `${process.env.API_INTERNAL_URL || 'http://lokilinux-api:8000'}/api/v1/**`,
      // Without this, the '/**' rule below's Cache-Control leaks onto proxied
      // API responses too — the browser then caches GETs (job lists, counts,
      // statuses) for an hour and silently serves stale data on every
      // subsequent request to the same URL, indistinguishable from a real bug.
      headers: { 'Cache-Control': 'no-store' },
    },
    // Default: never cache. Authenticated SSR pages and the Better Auth
    // session endpoints under /api/auth/** carry request-specific session
    // data — a public cache here would let one user's browser (or a shared
    // proxy) serve another user's session/HTML.
    '/**': {
      headers: { 'Cache-Control': 'no-store' },
    },
    // Nuxt's own build output is content-hashed and genuinely immutable —
    // this narrower, more specific rule overrides the no-store default above.
    '/_nuxt/**': {
      headers: { 'Cache-Control': 'public, max-age=3600' },
    },
  },

  nitro: {
    // node-server preset runs on node:22 (see Dockerfile) — bump esbuild's
    // default es2019 target so top-level await compiles (server/utils/auth.ts
    // reads Platform Settings from Postgres at module load).
    esbuild: {
      options: { target: 'node22' },
    },
  },

  runtimeConfig: {
    betterAuthSecret: process.env.BETTER_AUTH_SECRET || '',
    // Server-side (SSR) reaches the API container directly over the internal network.
    apiInternal: `${process.env.API_INTERNAL_URL || 'http://lokilinux-api:8000'}/api/v1`,
    public: {
      // Client-side base — relative, resolved same-origin and proxied by Nitro.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api/v1',
    },
  },

  typescript: {
    strict: true,
    typeCheck: false,
  },
})
