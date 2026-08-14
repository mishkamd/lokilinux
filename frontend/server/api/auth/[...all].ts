import { auth } from "~/server/utils/auth"

export default defineEventHandler((event) => {
  // Nothing sits between the browser and this Nitro server (docker-compose
  // maps the frontend port directly, no nginx/ALB in front), so there is no
  // trusted proxy that could legitimately set x-forwarded-for — any value
  // the client sends is spoofable and would let it evade better-auth's
  // per-IP rate limiter (which only ever reads that header, never the raw
  // socket) by rotating a fake IP. Always overwrite with the real TCP peer
  // address instead of only filling it in when absent.
  const request = toWebRequest(event)
  const ip = getRequestIP(event)
  if (ip) {
    request.headers.set("x-forwarded-for", ip)
  } else {
    request.headers.delete("x-forwarded-for")
  }
  return auth.handler(request)
})
