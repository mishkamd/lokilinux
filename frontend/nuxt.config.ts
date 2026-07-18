import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  ssr: true,
  compatibilityDate: '2024-11-01',

  app: {
    head: {
      meta: [{ name: 'color-scheme', content: 'dark light' }],
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

  nitro: {
    compression: 'gzip',
    headers: {
      'Cache-Control': 'public, max-age=3600',
    },
    // node-server preset runs on node:22 (see Dockerfile) — bump esbuild's
    // default es2019 target so top-level await compiles (server/utils/auth.ts
    // reads Platform Settings from Postgres at module load).
    esbuild: {
      options: { target: 'node22' },
    },
  },

  routeRules: {
    // Same-origin proxy: browser hits /api/v1/** on the Nuxt origin, Nitro forwards
    // to the FastAPI container. One public URL fronts frontend + API (no CORS).
    '/api/v1/**': {
      proxy: `${process.env.API_INTERNAL_URL || 'http://lokilinux-api:8000'}/api/v1/**`,
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
