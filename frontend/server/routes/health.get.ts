// Lightweight liveness probe for the container healthcheck — served at /health,
// which the auth middleware allowlists, so it isn't redirected to login.
// Avoids rendering the full SSR page on every check.
export default defineEventHandler(() => ({ status: 'ok' }))
