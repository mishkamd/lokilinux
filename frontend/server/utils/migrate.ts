/**
 * Script de migrare Better Auth — rulează în container pentru a crea tabelele.
 * Se execută cu: npx tsx server/utils/migrate.ts
 */
import { getMigrations } from "better-auth/db/migration"
import { auth } from "./auth"

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options)

if (toBeCreated.length === 0 && toBeAdded.length === 0) {
  process.exit(0)
}

await runMigrations()
process.exit(0)
