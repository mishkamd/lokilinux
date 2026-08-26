# LokiLinux Repositioning — Implementation Plan

> **STATUS (2026-08-26): COMPLET.** Commits: `fff8951` Task 3 backend metadata · `31103a5` Task 4 frontend branding + error.vue · `812c750` Task 5 packaging/deep docs · README rewrite (Task 1) + PRODUCT/DESIGN (Task 2) in the same window.
> **VALIDARE (2026-08-26):** old-term sweep repo-wide = zero hits în cod livrabil (doar `.aislop/worktrees/*` scratch); frontend vitest 102/102 + production build OK; backend pytest 380 passed; agent Go `-race` all-green (docker toolchain). Docker builds deliberately skipped (Task 6 note).

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Reposition LokiLinux from "Enterprise Linux Fleet Management" to **Enterprise Linux Operations Platform** across docs, UI copy, packaging metadata — zero functional/API/identifier changes.

**Architecture:** Copy/metadata-only refactor. Branding is already dynamic (`useBranding()` ← `settings_schema.branding.company_name`, stays `LokiLinux`). No routes, tables, env vars, container names, proto package touched.

**Tech stack:** Markdown, Vue/Nuxt, FastAPI metadata, nfpm YAML.

---

## Canonical strings (single source, used verbatim everywhere)

```
NAME       LokiLinux
CATEGORY   Enterprise Linux Operations Platform
TAGLINE    Secure. Automate. Operate.
DESC_LONG  Operate Linux infrastructure at scale through a unified control plane for fleet management, automation, security, PKI/KMS, observability, and AI-assisted operations.
DESC_SHORT Enterprise platform for secure and automated Linux infrastructure operations.
```

**Reality anchors (verified):** KMS implemented (`backend/lokilinux/kms/` — job signing, key lifecycle ACTIVE/VERIFY_ONLY/RETIRED, rotation endpoint, FileSigningProvider; Vault/HSM/PKCS#11 = explicit `NotImplementedError` future). PKI = mTLS CA + enrollment certs real; cert rotation planned (security ROADMAP). **AI: zero implementation** → appears ONLY as roadmap/future. Never claim otherwise.

---

### Task 1: README.md rewrite (first impression + honesty sections)

**Files:** Modify `README.md`

- [ ] Replace header block with identity block:

```markdown
<!-- generated-by: gsd-doc-writer -->
# LokiLinux

**Enterprise Linux Operations Platform**

> Secure. Automate. Operate.

Operate Linux infrastructure at scale through a unified control plane for fleet management,
automation, security, PKI/KMS, observability, and AI-assisted operations.
```

- [ ] Insert "Product Pillars" table after intro:

```markdown
## Product Pillars

| Pillar | What ships today |
|--------|------------------|
| **Operations** | Fleet inventory & health, patch management, service/host administration |
| **Automation** | Workflow engine (YAML + visual builder), Ansible layer, scheduled jobs |
| **Security** | RBAC (5 roles), audit log, signed jobs, mTLS everywhere |
| **PKI / KMS** | Job-signing keys with lifecycle + rotation (file provider); mTLS CA + enrollment certs |
| **Observability** | Events → signals → incidents pipeline, Prometheus metrics, alerts |
| **AI Operations** | Planned — see [Roadmap](#roadmap). Not implemented today. |
```

- [ ] Keep Features/Architecture/Quick Start bodies. Append KMS paragraph to "Security Hardening":

```markdown
- **KMS / signing**: every privileged job is Ed25519-signed; keys live in a versioned layout
  (`ACTIVE` / `VERIFY_ONLY` / `RETIRED`) with rotation via `POST /api/v1/admin/kms/keys/job-signing/rotate`.
  Provider interface defined for Vault / HSM / PKCS#11 — not implemented (explicit fail-closed `NotImplementedError`).
```

- [ ] Append Roadmap section before "Directory Structure":

```markdown
## Roadmap

Status labels are deliberate — nothing below is shipped.

| Area | Status | Notes |
|------|--------|-------|
| AI Operations | Planned | Diagnostics/RCA/remediation assistance behind policy engine + approvals. No AI code exists yet. |
| External KMS providers | Planned | Vault / PKCS#11 / cloud KMS — provider Protocol exists, implementations don't. |
| Certificate rotation | Planned | Short-lived agent certs + revocation endpoint (see docs/security/ROADMAP.md). |
| Debian/Ubuntu CVE sources | Backlog | CVE cross-referencing is dnf/yum-only today (agent/internal/modules/package_manager.go). |
```

- [ ] Commit: `docs: reposition README as Enterprise Linux Operations Platform`

### Task 2: PRODUCT.md + DESIGN.md

**Files:** Modify `PRODUCT.md`, `DESIGN.md`

- [ ] PRODUCT.md purpose line → operations-platform framing (mechanics kept).
- [ ] Brand Commitments tagline → `"Secure. Automate. Operate." / "Enterprise Linux Operations Platform"`; note fleet management stays a capability name.
- [ ] DESIGN.md frontmatter `description:` update.
- [ ] Commit: `docs: update product positioning and design-system description`

### Task 3: Backend metadata

**Files:** Modify `backend/lokilinux/main.py:232`, `backend/pyproject.toml:4`

- [ ] main.py: `description="Enterprise Linux Operations Platform — unified control plane API",`
- [ ] pyproject.toml: `description = "Enterprise Linux Operations Platform"` (NOTE: file has unrelated WIP OTLP dep — edit only line 4, do NOT stage this file; it rides with the pending OTLP commit)
- [ ] Verify: `cd backend && ruff check lokilinux/main.py`
- [ ] Commit only `backend/lokilinux/main.py`: `chore(backend): update OpenAPI metadata to operations-platform positioning`

### Task 4: Frontend branding surfaces

**Files:** Modify `frontend/nuxt.config.ts`, `frontend/layouts/auth.vue`, `frontend/pages/auth/login.vue`, `frontend/layouts/default.vue`; Create `frontend/error.vue`

- [ ] nuxt.config.ts meta description → DESC_LONG
- [ ] auth.vue subtitle → `Enterprise Linux Operations Platform`; footer → `{{ companyName }} — Secure. Automate. Operate.` (drops stale hardcoded v1.0)
- [ ] login.vue card subtitle → `Secure. Automate. Operate.`
- [ ] default.vue nav: label `'Dashboard'` → `'Overview'`; section title `'Automation Engine'` → `'Automation'`
- [ ] Create `frontend/error.vue` (branded 404/error using useBranding + Button + Home icon)
- [ ] Verify: `cd frontend && npm test`
- [ ] Commit: `feat(frontend): operations-platform branding on auth, metadata, nav labels; branded error page`

### Task 5: Packaging + deep docs

**Files:** Modify `agent/.nfpm.yaml`, `docs/ARCHITECTURE.md`, `docs/modules/00-index.md`, `docs/arhitecture/LOKILINUX_START_NOW.md`, `docs/arhitecture/LOKILINUX_OPTIMIZED_STACK.md`

- [ ] nfpm description → `LokiLinux — enterprise Linux operations agent`
- [ ] ARCHITECTURE.md platform-overview sentence → operations-platform identity
- [ ] modules/00-index.md RO positioning sentence → operațiuni pentru infrastructură Linux
- [ ] START_NOW.md "server management" → infrastructure operations wording
- [ ] OPTIMIZED_STACK.md ×2 Terraform descriptions → "Enterprise Linux operations platform"
- [ ] Commit: `docs: align architecture and module docs with operations-platform positioning`

### Task 6: Validation (no commit)

- [ ] Old-term sweep repo-wide (expect zero outside dated plan/snapshot dirs)
- [ ] Backend: ruff check + pytest tests/unit
- [ ] Frontend: npm test + npm run build
- [ ] Agent: make agent-test
- [ ] Docker builds skipped by decision

## Preserved (backward compat)

Container/image names, env vars, DB tables, API routes, proto package `lokilinux`, Go module paths, `branding.company_name` default/settings keys, `gen/proto/*`, sidebar routes, Romanian functional UI copy, dated plan/snapshot docs.
