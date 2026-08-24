# Plan — Modernizare Agent: Enterprise Policy Management

- **Data:** 2026-08-23
- **Scop:** Sistem Enterprise de Agent Policy Management — Control Plane = desired state, Agent = autonomous managed worker cu ultima politică validă local.
- **MVP livrabil:** Fazele 0–4. Faza 5 (signals/logs/buffer runtime) și Faza 6 (integrations) rămân iterații separate.
- **Decizii blocate (2026-08-23):**
  1. Multi-tenancy: **single-tenant, schema-ready** (`tenant_id` coloane default din ziua 1, izolare la query layer; tenancy reală = proiect separat).
  2. **Faza 0 = curățenia P0** din `docs/remediation/2026-08-23-dead-code-cleanup-plan.md` rulează înainte de orice.
  3. MVP executabil = **Fazele 1–4**.
  4. Acest document = referința de execuție.

---

## 1. Analiza stării existente — ce se reutilizează

Regulă: nu se introduc mecanisme paralele. Extindem ce există.

| Componentă existentă | Locație | Reutilizare în acest proiect |
|---|---|---|
| Enrollment + mTLS certs | `backend/lokilinux/api/v1/routers/agent_install.py`, CA via `scripts/init-certificates.sh` | Bază pentru hardening (Faza 3). Token actual: Redis TTL-only, non-single-use, fără revocare → migrat în DB |
| Canal Agent↔CP | gRPC `HeartbeatStream` JSON-codec bidirecțional (`pending_jobs`↓, `resync_domains`↑) | `resync_domains` = precedentul exact pentru nudge; adăugăm `desired_policy_version` |
| JetStream | Doar în compliance service (`internal/*/consumer.go` `EnsureStream` pattern); backend are core-NATS publish only | Pattern copiat pentru stream nou `AGENT`; backend primește jetstream ctx |
| Naming NATS | `lokilinux/nats_topics.py`: `lokilinux.<domain>.<event>` | Subiecte noi `lokilinux.agent.policy.*` |
| Config injection pe colectori | `agent/internal/compliance/collector.go` `BuildRegistry(cfg)` pe 24 colectori | Mecanismul direct prin care policy controlează collection din ziua 1 |
| Persistență locală agent | `agent/internal/storage/sqlite.go` pattern `UpsertComplianceState`/`AllComplianceState` | Stare policy locală (`state.db`) |
| Capability gating | `backend/lokilinux/utils/agent_capability.py` `agent_meets_minimum(MIN_AGENT_VERSION_*)` | Back-compat: agenți vechi fără suport policy primesc zero notificări |
| Audit | `services/audit_service.py` + pattern `PolicyAudit` (models/policy.py) | Tabela `agent_policy_audit` + log_action |
| RBAC | `auth/dependencies.py` `require_role` | Toate endpoint-urile noi |
| API patterns | Routere `/api/v1` + `CursorPage` pagination | Toate endpoint-urile noi |
| Frontend editor YAML | CodeMirror `@codemirror/lang-yaml` deja folosit în workflow editor | Policy YAML editor |
| Frontend patterns | stores Pinia, pagini admin, badge/drift UI din compliance drift page | Pagini Agent Policies / per-agent policy panel |

**Coliziune de nume — evitată prin convenție:** `Policy` existent (automatizări UPDATE/SECURITY cron) rămâne neatins. Noul concept se numește **`AgentPolicy`** peste tot: tabele `agent_policies*`, module `agent_policies.py`, router `agent_policies.py`.

**Multi-tenancy:** NU există în repo astăzi (zero `tenant_id`). Decizia: single-tenant MVP; toate tabelele noi primesc `tenant_id UUID NOT NULL DEFAULT gen_random_uuid()`-backed constant `'default'` (coloană + index), filtrare la query layer din prima linie de cod, astfel încât tenancy reală ulterior să fie o migrare de date, nu un redesign.

## 2. Arhitectura țintă

```text
                LokiLinux Control Plane
                          │
                  Admin Panel (UI)
                          │
                  Policy Manager (API)
                          │
                     PostgreSQL          ← sursa de adevăr (desired state)
                          │
                  Policy Compiler + Sign (ed25519)
                          │
                  NATS JetStream stream "AGENT"
           lokilinux.agent.policy.updated.{agent_id}   ← notificare MICĂ
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
     Agent01           Agent02           Agent03
        │
   VERIFY (issuer, ed25519, key_id, sha256, version)
   VALIDATE (schema + semantică)
   FETCH complet prin gRPC mTLS existent (RPC GetPolicy)
   STAGE → APPLY → HEALTH CHECK → COMMIT (atomic)
        │
        └── heartbeat payload + lokilinux.agent.policy.applied.{agent_id}
                                    ↓
                          Control Plane (PolicyStatusWorker)
```

Principii (nerenegociabile):

```text
Control Plane = Desired State      PostgreSQL = source of truth
Agent         = Actual State       NATS       = transport/notificare, NICIODATĂ database
Agent         = autonomous worker  mTLS+semnături = securitate, NATS ≠ security boundary
```

## 3. Schema PostgreSQL — migrația `030_add_agent_policy_management`

Toate tabelele noi: `tenant_id UUID NOT NULL` (default tenant), FK-uri conforme stilului existent (created_by UUID fără FK — users sunt în Better Auth).

```text
agent_policies
    id UUID PK, tenant_id, name UNIQUE(tenant_id,name), description,
    status TEXT draft|active|archived, current_version INT nullable,
    created_by UUID, created_at, updated_at

agent_policy_versions                       -- IMMUTABIL după publish
    id UUID PK, policy_id FK CASCADE, version INT, payload JSONB,
    payload_hash TEXT (sha256), signature TEXT (base64 ed25519),
    signing_key_id TEXT, status TEXT draft|published,
    created_by UUID, created_at, UNIQUE(policy_id, version)

agent_policy_assignments
    id UUID PK, tenant_id, policy_id FK, version_id FK nullable (=current dacă null),
    scope_type TEXT AGENT|GROUP|TENANT, scope_ref UUID nullable,
    rollout_strategy TEXT immediate|canary|percentage, rollout_config JSONB default {},
    enabled BOOL default true, created_by, created_at
    -- extensibil spre inheritance Default→Environment→Group→Host fără migrare de shape

agent_policy_deployments
    id UUID PK, tenant_id, assignment_id FK, agent_id FK, version_id FK,
    status TEXT pending|delivered|applied|failed|rolled_back,
    error TEXT nullable, started_at, finished_at

enrollment_tokens                            -- migrare din Redis ephemeral
    id UUID PK, token_hash TEXT UNIQUE (sha256, token-ul clar nu se stochează),
    label TEXT, expires_at TIMESTAMPTZ, used_at nullable, revoked_at nullable,
    single_use BOOL default true, agent_group UUID nullable (FK agent_groups)

agent_groups            id UUID PK, tenant_id, name, created_at

ALTER agents ADD:
    desired_policy_version_id UUID NULL, current_policy_version_id UUID NULL,
    policy_status TEXT idle|syncing|pending|failed default 'idle',
    policy_last_error TEXT NULL, policy_updated_at TIMESTAMPTZ NULL

agent_policy_audit      id BIGSERIAL PK, actor UUID NULL, action TEXT
    (create|update|publish|assign|deploy|apply_ok|apply_fail|rollback|revoke_token),
    resource_type TEXT, resource_id UUID, old_version INT NULL, new_version INT NULL,
    result TEXT ok|fail, error TEXT NULL, created_at  -- fără secrets
```

Seed la migrare: tenant implicit + `Default Bootstrap Policy v1` (status active, payload minimal) + templates `linux-minimal`, `linux-standard`, `linux-production`.

## 4. Policy schema (`apiVersion: lokilinux.io/v1`, `kind: AgentPolicy`)

Structura e adaptată capacităților REALE ale agentului; secțiunile runtime noi se validează din ziua 1 dar devin active în Faza 5 — protocolul nu se schimbă ulterior.

```yaml
apiVersion: lokilinux.io/v1
kind: AgentPolicy
metadata:
  name: production-linux
spec:
  collectors:                    # cele 24 domenii reale din BuildRegistry
    auditd: { enabled: true }
    sshd:   { enabled: true }
    users:  { enabled: true }
    # ... orice subset; nespecificat = disabled (deny-by-default)
  heartbeat: { interval_seconds: 30 }          # limite: 10..300
  health: { collect_interval_seconds: 30 }      # CollectHealth existent
  signals:                                       # NOU — activ în Faza 5
    rules:
      - { id: oom-killer, source: journal, severity: critical, enabled: true }
      - { id: ssh-bruteforce, source: journal, match: "sshd.*Failed password",
          threshold: { count: 10, window_seconds: 60 }, severity: high }
  services: { monitor: [nginx, postgresql] }     # NOU — Faza 5
  logs: { journald: { enabled: false, minimum_priority: err } }  # NOU — Faza 5
  limits: { events_per_second: 100, logs_per_second: 50 }        # NOU — Faza 5
  buffer: { enabled: true, max_size_mb: 500 }                    # NOU — Faza 5
  compliance: {}                                 # passthrough viitor (CIS etc.)
  otel: {}                                       # rezervat — fără redesign
```

Validare strictă: `apiVersion` cunoscut obligatoriu; câmpuri necunoscute ⇒ reject (nu warn); intervale numerice clamp-uite la bounds definite în schema; dimensiune max payload 1 MB.

## 5. NATS — subiecte și payloads

Stream nou **`AGENT`**: subjects `lokilinux.agent.>`, MaxAge 24h (pattern `EnsureStream` copiat din compliance consumer).

| Subiect | Direcție | Payload |
|---|---|---|
| `lokilinux.agent.policy.updated.{agent_id}` | CP→agent | `{ "policy_id": "...", "version": 18, "hash": "sha256:..." }` — notificare mică; agentul face fetch |
| `lokilinux.agent.policy.applied.{agent_id}` | agent→CP | `{ "policy_id", "version", "result": "applied", "duration_ms" }` |
| `lokilinux.agent.policy.failed.{agent_id}` | agent→CP | `{ "policy_id", "version", "error_code", "error" }` |
| `lokilinux.signals.{rule_id}` (Faza 5-6) | agent→CP | signal events pentru correlation |

Fallback de reconciliere: heartbeat response primește câmp suplimentar `desired_policy_version` — acoperă cazul „JetStream jos, gRPC sus" și reconcilierea la reconectare (§15 din cerință).

Consumator CP: worker nou `workers/policy_status_worker.py` (pattern workers existent, pornit în lifespan lângă celelalte) actualizează `agent_policy_deployments` + coloanele pe `agents`.

## 6. API endpoints (`/api/v1`, CursorPage, require_role, tenant-scoped)

```text
# Policies
GET    /agent-policies                        list (CursorPage)
POST   /agent-policies                        create (draft)
GET    /agent-policies/{id}                   detail (+versions summary)
PUT    /agent-policies/{id}                   edit DOAR pe draft; published ⇒ nouă versiune
DELETE /agent-policies/{id}                   archived only, fără assignments active
POST   /agent-policies/{id}/clone
GET    /agent-policies/{id}/versions
POST   /agent-policies/{id}/versions          create draft version din payload
POST   /agent-policies/{id}/publish           {version_id} → semnează, immutable, status active
GET    /agent-policies/{id}/audit

# Templates
GET    /agent-policy-templates
POST   /agent-policies/from-template          {template_key, name}

# Assignment & Deployment
GET/POST  /agent-policies/{id}/assignments
DELETE    /assignments/{id}
POST   /agent-policies/{id}/deploy            {scope_type, scope_ref?, rollout_strategy?}
POST   /agents/{id}/policy/deploy             deploy direct pe un agent
POST   /agents/{id}/policy/rollback           {to_version} ⇒ deployment NOU (istoricul nu se atinge)
GET    /agents/{id}/policy                    effective policy + desired vs actual
GET    /agents/{id}/policy/status             deployment status + last error
POST   /agents/{id}/policy/sync-now           force reconcile

# Groups & enrollment
GET/POST  /agent-groups
GET/POST  /enrollment-tokens                  create: {label, ttl, single_use, agent_group?}
DELETE    /enrollment-tokens/{id}             revocare
```

gRPC nou pe dial-ul mTLS existent (JSON codec): `GetPolicy(agent_id, current_version_id) → envelope complet sau 304-not-modified`.

## 7. Runtime agent — pachet nou `internal/policy/`

Lifecycle (fără apply direct niciodată):

```text
RECEIVE (subscriber NATS + desired_policy_version din heartbeat)
  → VERIFY      issuer=lokilinux-control-plane, ed25519 signature, key_id ∈ trusted keys,
                sha256(payload)==hash, version > current (monotonică; downgrade respins
                except when signed force flag from CP)
  → VALIDATE    schema strictă + semantică (intervale, domenii colectori cunoscute)
                FAIL ⇒ DO NOT APPLY, ultima politică validă rămâne ACTIVĂ
  → COMPILE     payload → structuri interne validate
  → STAGE       scriere în fișier temporar + fsync
  → APPLY       BuildRegistry cu config nou + heartbeat interval + health interval
  → HEALTH CHECK  un ciclu de colectare reușit
  → COMMIT      atomic rename staged→active; stare persistată
```

Fișiere noi:

```text
agent/internal/policy/parser.go      yaml→struct + validare
agent/internal/policy/verify.go      ed25519 + hash + version monotonic
agent/internal/policy/store.go       /var/lib/lokilinux-agent/policy.{json,version,hash,signature}
                                     scriere atomică (tmp+rename), permisiuni 0600, dir 0700
agent/internal/policy/state.go       desired vs current vs status (sqlite, pattern ComplianceState)
agent/internal/policy/apply.go       stage/apply/health/commit + rollback-to-last-good
agent/internal/communication/nats_sub.go   subscriber JetStream durable per-agent
```

Hook-uri minime în cod existent: `manager.go` (pornește subscriber, verifică desired version în heartbeat loop, reconciliere LA PORNIRE — încarcă policy.json local înainte de primul contact), `grpc_client.go` (+GetPolicy), `config.go` (+secțiune opțională `policy:` cu trusted_keys dir; sync obligatoriu cu `install_agent.sh.tmpl`).

Stare locală:

```text
/var/lib/lokilinux-agent/          0700 (postinstall creează)
├── policy.json .version .hash .signature   0600
├── state.db                      sqlite existent
└── buffer/                       Faza 5
```

Offline behavior: NATS/API/CP/internet down ⇒ continuă pe last-known-good. Reconnect ⇒ heartbeat → compare versions → fetch → apply → flush buffer. Idempotență: aceeași version primită de N ori ⇒ aplicată o singură dată.

## 8. Security model

- Transport: mTLS existent (certs per-agent de la enrollment) — neatinse.
- Semnare politici: keypair **ed25519 dedicat** generat de `docker-init.sh` (`policy-signing-key`), separat de CA TLS; `signing_key_id` în envelope; public key pinned în `agent.yaml` la enrollment; rotație = director trusted_keys cu multiple keys valide.
- Verificare agent (în ordinea asta): issuer → signature → policy_id așteptat → version monotonică → hash → schema → semantică. Orice fail ⇒ reject + raport `policy.failed`.
- Replay/idempotency: version monotonică + deployment idempotent (aceeași version ⇒ no-op).
- Enrollment hardening (Faza 3): tokens în DB (hash-only), single-use opțional/default, revocare, expirare, binding pe grup.
- Permisiuni locale: dir 0700, fișiere 0600.
- RBAC: ADMIN/OPERATOR pt management policy; agent endpoints doar cu mTLS identity.
- Audit: fiecare operațiune din §22 → `agent_policy_audit`, fără secrets.

## 9. Deployment & rollback flows

Deploy: admin creează/modifică assignment → POST deploy → CP persistă desired (assignments + agents.desired_policy_version_id) → publish notificare per-agent (respectând rollout_strategy: `immediate` în MVP; `canary`/`percentage` doar câmpuri rezervate) → agent fetch/verify/apply → applied/failed → deployments + audit.

Rollback: POST rollback {to_version} ⇒ deployment NOU către versiunea anterioară (versiunile vechi nu se șterge niciodată). Drift vizibil permanent în UI: `Desired v18 / Actual v17 / ⚠ out of sync [Sync Now]`.

## 10. Back-compat & breaking changes

- **Zero breaking changes.** Agenții existente (< versiune policy) nu au subscriber/RPC — CP le sare notificările prin `agent_meets_minimum(MIN_AGENT_VERSION_POLICY)` (utilitar existent); funcționează exact ca azi.
- `agent.yaml` primește secțiune opțională `policy:` — config vechi rămâne valid.
- Endpoint-uri existente neatinse; noul router e adițional.
- Migrația 030 e pur adițională (ADD tables/columns), fără modificări pe tabele existente except ALTER agents (coloane nullable).

## 11. Matrice teste failure scenarios (obligatorii pentru acceptanță)

Go agent (`internal/policy/*_test.go`):
`TestVerify_InvalidSignature_Rejected`, `TestVerify_WrongIssuer_Rejected`, `TestVersion_DowngradeRejected`, `TestVersion_Duplicate_Idempotent`, `TestValidate_UnknownField_Rejected`, `TestApply_CorruptedHash_Rejected`, `TestCommit_Atomic_RestartMidApply_LastGoodActive`, `TestOffline_LastGoodPolicyRuns24h`, `TestReconnect_ReconcileAndFetchLatest`, `TestTrustedKeys_Rotation`.

Backend integration (pytest + testcontainers):
`TestPublish_Immutability`, `TestDeploy_Fanout_ManyAgents`, `TestDeploy_Duplicate_SingleDeployment`, `TestEnrollToken_SingleUse_Expiry_Revocation`, `TestStatusWorker_AppliedAndFailed`, `TestLargePayload_Rejected1MB`, `TestOldAgent_NoNotifications` (capability gate).

Frontend (vitest): drift badge states, rollback flow, YAML editor validation errors.

## 12. Observability

Backend/compliance-style counters: `lokilinux_policy_deployments_total`, `lokilinux_policy_apply_success_total`, `_failure_total`, `_validation_failures_total`, `lokilinux_agent_policy_drift` (gauge), `lokilinux_policy_sync_duration_seconds`. Agent: statistici policy în heartbeat payload (versiune, ultimul status); metrics endpoint propriu = Faza 6/OTel.

## 13. Faze de implementare

### Faza 0 — Prereq: curățenie P0 (din remediation plan)
Execută Faza 1 din `docs/remediation/2026-08-23-dead-code-cleanup-plan.md`. Verificare: `make agent-test`, `make compliance-test`, pytest, `npm test && npm run build`.

### Faza 1 — Foundation (~3-4 z)
Backend: migrația 030; models + Pydantic schemas; router `agent_policies.py` CRUD+versions+publish+clone+templates seed; generare keypair signing în docker-init.sh; semnătură la publish (cryptography ed25519). Agent: `internal/policy/{parser,store}.go` + fallback policy compiled-in; hook citire config `policy:`; tmpl sync. Frontend: pagina `admin/agent-policies` (listă + editor CodeMirror YAML + validare), seed templates vizibile.
Acceptanță: CRUD + publish funcțional end-to-end; parser respinge payload invalid; suite verzi.

### Faza 2 — Distribution (~3-4 z)
Backend: stream AGENT + publisher jetstream; RPC `GetPolicy` în grpc_server/agent_service; `desired_policy_version` în heartbeat response; `policy_status_worker.py`; coloanele desired/current populate. Agent: `nats_sub.go`, verify+validate complete, lifecycle stage/apply/commit + reconciliere la pornire, raportare applied/failed. Frontend: panou policy pe pagina agent (desired vs actual, status, last error).
Acceptanță: fluxul complet Install→Enroll→Assign→Deploy→Apply→Report pe un agent real; duplicate message = no-op; offline 24h = continuă pe last-known-good.

### Faza 3 — Security (~2-3 z)
Verificare semnătură end-to-end (agent respinge unsigned/bad-key); downgrade protection; enrollment tokens → DB (migrare din Redis-only), single-use, revocare, grup binding; permisiuni 0700/0600; rotație trusted keys.
Acceptanță: matricea de teste signature/downgrade/token verde.

### Faza 4 — Enterprise Management (~3-4 z)
Grupuri (tabelă + UI), assignments pe AGENT/GROUP/TENANT scope, deploy modal cu rollout_strategy (immediate live; canary/percentage rezervate în UI ca „soon"), rollback UI, view audit, badge drift „⚠ out of sync / Sync Now", pagina per-agent policy conform UX §24 din cerință.
Acceptanță: criteriile §39 (fazele 1-4) bifate integral.

### Faza 5 — Agent Runtime (iterație următoare)
Signals engine (journal), service monitoring, log filtering journald, rate limiting, buffer + flush la reconnect. Activează secțiunile deja validate din schemă.

### Faza 6 — Integrations (iterație următoare)
Subiecte `lokilinux.signals.*` pentru Event Correlation, secțiunea `compliance:` passthrough (profile CIS), hook OTel rezervat, metrics endpoint agent.

## 14. Criterii de acceptanță MVP (Fazele 0-4)

- agent nou instalabil bootstrap-minimal; enrolled; apare în Admin Panel;
- admin creează/versionează/publică/asignează/deploy/rollback policy;
- distribuție exclusiv prin JetStream notification + fetch gRPC mTLS;
- agentul verifică issuer/signature/hash/schema/version înainte de apply;
- apply atomic cu health check; fail ⇒ ultima politică validă rămâne activă;
- desired vs actual vizibil; sync-now funcțional;
- offline = autonom pe last-known-good; reconnect = reconciliere;
- duplicate messages safe; rollback = deployment nou;
- audit trail complet; RBAC + tenant_id pe toate rutele/tabelele noi;
- agenți vechi neafectați (capability gate); zero breaking changes;
- matricea de teste failure verde; fără al doilea messaging/enrollment mechanism.
