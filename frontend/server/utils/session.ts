import type { H3Event } from "h3"
import { auth } from "./auth"

export async function getSession(event: H3Event) {
  return auth.api.getSession({ headers: event.headers })
}
