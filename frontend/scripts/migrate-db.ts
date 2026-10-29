/**
 * One-shot Better Auth migration — run from HOST: npx tsx scripts/migrate-db.ts
 *
 * Uses Better Auth's official migration engine (getMigrations), which derives
 * the FULL schema from the configured plugins (username, twoFactor, admin, ...).
 * This is the single source of truth — do NOT hand-roll CREATE TABLE statements,
 * they drift from plugin requirements (missing role/displayUsername/impersonatedBy
 * columns is exactly what broke sign-up before).
 *
 * Admin user creation is handled separately by scripts/docker-init.sh via the
 * sign-up endpoint, so credentials go through Better Auth's own hashing.
 */
import { betterAuth } from "better-auth"
import { username, twoFactor, bearer, admin } from "better-auth/plugins"
import { getMigrations } from "better-auth/db/migration"
import { PostgresDialect } from "kysely"
import pg from "pg"

const { Pool } = pg

// NOTE: getMigrations only works with Better Auth's *built-in* kysely support
// (a Dialect passed directly), not the external @better-auth/kysely-adapter that
// runtime auth.ts uses. Both target the same tables, so the generated schema is
// identical — this instance exists purely to compute/run migrations.
// Default target is the host-published pgbouncer (127.0.0.1:6432). docker-init.sh
// runs this inside a container on the data network instead, where pgbouncer is
// reachable as lokilinux-pgbouncer:5432, and passes MIGRATE_DB_HOST/PORT for that.
// Do NOT read POSTGRES_HOST here: that's the in-container hostname from .env.
const pool = new Pool({
  host: process.env.MIGRATE_DB_HOST || "127.0.0.1",
  port: Number(process.env.MIGRATE_DB_PORT || 6432),
  user: process.env.POSTGRES_USER || "lokilinux",
  password: process.env.POSTGRES_PASSWORD,
  database: process.env.POSTGRES_DB || "lokilinux",
})

const dialect = new PostgresDialect({ pool })

// Same plugin set as server/utils/auth.ts — keep in sync so migrations match runtime.
const auth = betterAuth({
  database: { dialect, type: "postgres" },
  secret: process.env.BETTER_AUTH_SECRET,
  baseURL: process.env.BETTER_AUTH_URL || "http://localhost:3000",
  plugins: [username(), twoFactor(), bearer(), admin()],
  emailAndPassword: { enabled: true, requireEmailVerification: false },
})

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options)

console.log("Tables to create:", toBeCreated.map((t) => t.table))
console.log("Columns to add:", toBeAdded.map((t) => t.table))

if (toBeCreated.length === 0 && toBeAdded.length === 0) {
  console.log("✅ Better Auth schema is up to date")
} else {
  await runMigrations()
  console.log("✅ Better Auth migrations applied")
}

// `account.issuer` is a leftover column from an older Better Auth release — the
// current one (1.6) never writes it, but the column is NOT NULL, so every
// sign-up died with "null value in column issuer". Relax it (idempotent, and a
// no-op on a fresh DB where the column does not exist).
// ponytail: keeps the column instead of dropping it — DROP COLUMN is the clean
// fix but only safe once nothing reads it; revisit if the schema is ever rebuilt.
await pool.query(`DO $$ BEGIN
  ALTER TABLE "account" ALTER COLUMN "issuer" DROP NOT NULL;
EXCEPTION WHEN undefined_column THEN NULL;
END $$;`)
console.log("✅ account.issuer relaxed (legacy NOT NULL)")

process.exit(0)
