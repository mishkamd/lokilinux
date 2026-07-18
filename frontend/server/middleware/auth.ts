import { auth } from "~/server/utils/auth"

export default defineEventHandler(async (event) => {
  const path = getRequestURL(event).pathname

  if (
    path.startsWith('/auth/') ||
    path.startsWith('/api/auth/') ||
    path.startsWith('/_nuxt/') ||
    path === '/health' ||
    path.startsWith('/favicon')
  ) return

  const session = await auth.api.getSession({ headers: event.headers })

  if (!session) {
    await sendRedirect(event, '/auth/login', 302)
  }
})
