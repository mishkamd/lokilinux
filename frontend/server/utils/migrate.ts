/**
 * Script de migrare Better Auth — rulează în container pentru a crea tabelele.
 * Se execută cu: npx tsx server/utils/migrate.ts
 */
import { getMigrations } from "better-auth/db/migration"
import { auth } from "./auth"

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options)

console.log("Tables to create:", toBeCreated)
console.log("Columns to add:", toBeAdded)

if (toBeCreated.length === 0 && toBeAdded.length === 0) {
  console.log("✅ Schema is up to date")
  process.exit(0)
}

await runMigrations()
console.log("✅ Migrations applied successfully")
process.exit(0)
