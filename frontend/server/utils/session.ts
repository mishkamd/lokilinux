import type { H3Event } from "h3"
import { auth } from "./auth"

export async function getSession(event: H3Event) {
  return auth.api.getSession({ headers: event.headers })
}

export async function requireSession(event: H3Event) {
  const session = await getSession(event)
  if (!session) throw createError({ statusCode: 401, message: "Unauthorized" })
  return session
}
