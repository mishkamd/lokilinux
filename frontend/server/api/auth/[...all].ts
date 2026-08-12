import { auth } from "~/server/utils/auth"

export default defineEventHandler((event) => {
  // Nothing sits between the browser and this Nitro server (docker-compose
  // maps the frontend port directly, no nginx/ALB in front), so the browser
  // never sends x-forwarded-for and better-auth's rate limiter (which only
  // ever reads that header, never the raw socket) falls back to a single
  // shared bucket for every client — confirmed live via its own
  // "could not determine a client IP" warning. getRequestIP reads the real
  // TCP peer address directly, which is trustworthy precisely because
  // there's no proxy hop to spoof it at.
  const request = toWebRequest(event)
  if (!request.headers.has("x-forwarded-for")) {
    const ip = getRequestIP(event)
    if (ip) request.headers.set("x-forwarded-for", ip)
  }
  return auth.handler(request)
})
