import { betterAuth } from "better-auth"
import { kyselyAdapter } from "@better-auth/kysely-adapter"
import { username, twoFactor, bearer, admin } from "better-auth/plugins"
import { Kysely, PostgresDialect } from "kysely"
import pg from "pg"

const { Pool } = pg

// ponytail: parametri expliciți — parola poate conține / sau @ care sparge URL parsing
const pool = new Pool({
  host: process.env.POSTGRES_HOST || "pgbouncer",
  port: parseInt(process.env.POSTGRES_PORT || "5432"),
  user: process.env.POSTGRES_USER,
  password: process.env.POSTGRES_PASSWORD,
  database: process.env.POSTGRES_DB || "lokilinux",
})

const db = new Kysely({
  dialect: new PostgresDialect({ pool }),
})

// ponytail: read once at module load — better-auth's config is built a single
// time, so changes made in Platform Settings take effect on next restart, not
// live. Falls back to these defaults if `settings` isn't reachable yet (e.g.
// first boot, before lokilinux-migrate has run).
const SECURITY_DEFAULTS = {
  sessionExpiryDays: 7,
  sessionUpdateAgeHours: 24,
  passwordMinLength: 8,
  companyName: "LokiLinux",
}

async function loadSecuritySettings() {
  try {
    const { rows } = await pool.query<{ key: string; value: string }>(
      "SELECT key, value FROM settings WHERE key = ANY($1)",
      [[
        "security.session_expiry_days",
        "security.session_update_age_hours",
        "security.password_min_length",
        "branding.company_name",
      ]],
    )
    const map = Object.fromEntries(rows.map((r) => [r.key, r.value]))
    return {
      sessionExpiryDays: Number(map["security.session_expiry_days"]) || SECURITY_DEFAULTS.sessionExpiryDays,
      sessionUpdateAgeHours: Number(map["security.session_update_age_hours"]) || SECURITY_DEFAULTS.sessionUpdateAgeHours,
      passwordMinLength: Number(map["security.password_min_length"]) || SECURITY_DEFAULTS.passwordMinLength,
      companyName: map["branding.company_name"] || SECURITY_DEFAULTS.companyName,
    }
  } catch {
    return SECURITY_DEFAULTS
  }
}

const security = await loadSecuritySettings()

export const auth = betterAuth({
  database: kyselyAdapter(db, { type: "postgres" }),
  secret: process.env.BETTER_AUTH_SECRET,
  baseURL:
    process.env.BETTER_AUTH_URL ||
    (process.env.NODE_ENV === "production"
      ? (() => {
          throw new Error("Missing required env var BETTER_AUTH_URL in production")
        })()
      : "http://localhost:3000"),
  // ponytail: BETTER_AUTH_URL e un singur hostname (ex IP LAN), dar platforma
  // e accesată și via localhost/alte hostname-uri — origin check respinge orice
  // altceva cu 403 pe POST-uri autenticate. Trustedorigins acoperă ambele.
  trustedOrigins: [
    process.env.BETTER_AUTH_URL,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
  ].filter((v): v is string => Boolean(v)),
  plugins: [
    username(),
    twoFactor({ issuer: security.companyName }),
    bearer(),
    admin(),
  ],
  session: {
    expiresIn: 60 * 60 * 24 * security.sessionExpiryDays,
    updateAge: 60 * 60 * security.sessionUpdateAgeHours,
  },
  emailAndPassword: {
    enabled: true,
    requireEmailVerification: false,
    minPasswordLength: security.passwordMinLength,
  },
})
