<!-- generated-by: gsd-doc-writer -->
# API Reference

LokiLinux exposes two APIs:

- **REST API** (FastAPI) — mounted at `/api/v1`, used by the Nuxt frontend and any external integrations.
- **gRPC API** (mTLS) — port `50051`, used exclusively by the Go agent for heartbeats.

## Authentication

### REST API

All REST endpoints (except `agent-install` package/script/enrollment routes used by unauthenticated bootstrap flows — see below) require a Bearer token:

```
Authorization: Bearer <token>
```

The token is an **opaque Better Auth session token**, not a JWT. `lokilinux/auth/jwks_validator.py::get_current_user` validates it by calling:

```
GET {BETTER_AUTH_URL}/api/auth/get-session
Authorization: Bearer <token>
```

Behavior:
- A successful session is cached in Redis for 60s (`ba:session:{token}`) to avoid hitting Better Auth on every request.
- If the auth service is unreachable, a request is retried once after a 1s delay; on repeated failure a negative cache entry (`ba:down:{token}`, 5s TTL) short-circuits further calls and the API returns `503 Auth service unavailable`.
- `401` is returned for a missing/invalid header or an expired/invalid session.
- The user's `role` is normalized to uppercase for comparison against role checks.

### Role-based access

`lokilinux/auth/dependencies.py::require_role(*roles)` wraps `get_current_user` and enforces that the caller's role is `ADMIN` or is one of the roles passed to the factory; otherwise it returns `403 Insufficient permissions`. Roles in use: `ADMIN`, `OPERATOR`, `AUDITOR`, `MANAGER`, `VIEWER`.

Most read (`GET`) endpoints only require an authenticated session (any role). Mutating endpoints on servers, admin, plugins, alerts, and agent install typically require `ADMIN` or `OPERATOR`; some admin endpoints (user management, settings, agent-config write) require `ADMIN` only; the audit log endpoint requires `ADMIN` or `AUDITOR`.

### Plugin-gated routes

The Ansible Automation routers (`playbooks`, `playbook-templates`, `ansible-roles`, `ansible-projects`) additionally depend on `require_plugin_enabled("ansible-automation")` (`lokilinux/api/v1/routers/playbooks.py`). This queries the `plugins` table on every request and returns `403` if the `ansible-automation` plugin row is not `is_enabled`.

## Base URL and routing

All routers are mounted under `/api/v1` in `lokilinux/main.py` via `app.include_router(api_v1_router, prefix="/api/v1")`. The router prefixes below are relative to `/api/v1`.

| Router file | Prefix | Tag |
|---|---|---|
| `routers/dashboard.py` | `/dashboard` | dashboard |
| `routers/categories.py` | *(no prefix — routes define their own `/categories`, `/projects`)* | categories |
| `routers/servers.py` | `/servers` | servers |
| `routers/jobs.py` | `/jobs` | jobs |
| `routers/cves.py` | `/vulnerabilities` | vulnerabilities |
| `routers/policies.py` | `/policies` | policies |
| `routers/plugins.py` | `/plugins` | plugins |
| `routers/playbooks.py` | `/playbooks` | playbooks |
| `routers/playbook_templates.py` | `/playbook-templates` | playbook-templates |
| `routers/ansible_roles.py` | `/ansible-roles` | ansible-roles |
| `routers/ansible_projects.py` | `/ansible-projects` | ansible-projects |
| `routers/alerts.py` | `/alerts` | alerts |
| `routers/admin.py` | `/admin` | admin |
| `routers/agent_install.py` (`router`) | `/agent` | agent-install |
| `routers/agent_install.py` (`register_router`) | `/agents` | agent-install |

## Endpoints

### Dashboard — `/api/v1/dashboard`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/summary` | session | Aggregate fleet summary (agent counts, jobs, CVEs, alerts). |

### Categories & Projects — `/api/v1`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/categories` | session | List categories. |
| POST | `/categories` | ADMIN, OPERATOR | Create a category. |
| DELETE | `/categories/{category_id}` | ADMIN | Delete a category. |
| GET | `/projects` | session | List projects. |
| POST | `/projects` | ADMIN, OPERATOR | Create a project. |
| DELETE | `/projects/{project_id}` | ADMIN | Delete a project. |

### Servers (Agents) — `/api/v1/servers`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | session | Cursor-paginated agent list. Query params: `cursor`, `limit` (1-100, default 20), `status`, `search`. Returns `CursorPage[AgentResponse]`. |
| GET | `/{agent_id}` | session | Agent detail. |
| GET | `/{agent_id}/packages` | session | Installed packages on the agent (`list[PackageResponse]`). |
| GET | `/{agent_id}/metrics` | session | Latest `AgentHealthResponse`, or `null`. |
| POST | `/{agent_id}/maintenance` | session | Toggle maintenance mode on the agent. |
| PATCH | `/{agent_id}/assignment` | ADMIN, OPERATOR | Reassign agent's `category_id`/`project_id`. |

Agent status enum (`AgentStatus`): `PENDING`, `REGISTERED`, `ACTIVE`, `INACTIVE`, `UNHEALTHY`, `MAINTENANCE`.

### Jobs — `/api/v1/jobs`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | session | Cursor-paginated job list (`CursorPage[JobResponse]`). |
| POST | `` | session | Create/enqueue a job. Returns `201`. |
| GET | `/{job_id}` | session | Job detail. |
| GET | `/{job_id}/results` | session | Per-agent results for the job (`list[JobResultResponse]`). |
| POST | `/{job_id}/approve` | ADMIN, OPERATOR | Approve a job pending manual approval. |
| DELETE | `/{job_id}` | session | Cancel/delete a job. Returns `204`. |

Job status enum (`JobStatus`): `QUEUED`, `SCHEDULED`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `TIMEOUT`, `CANCELLED`.
Job type enum (`JobType`): `PACKAGE_UPDATE`, `SECURITY_PATCH`, `INVENTORY_SCAN`, `CVE_SCAN`, `CUSTOM_COMMAND`, `REMEDIATION`, `ANSIBLE_PLAYBOOK`.

### Vulnerabilities (CVEs) — `/api/v1/vulnerabilities`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | session | Cursor-paginated CVE list (`CursorPage[CVEResponse]`). |
| GET | `/{cve_id}` | session | CVE detail. |
| GET | `/servers/{agent_id}` | session | Vulnerabilities affecting a specific agent (`CursorPage[VulnerabilityResponse]`). |

### Policies — `/api/v1/policies`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | session | Cursor-paginated policy list. |
| POST | `` | session | Create a policy. Returns `201`. |
| GET | `/{policy_id}` | session | Policy detail. |
| PATCH | `/{policy_id}` | session | Update a policy. |
| DELETE | `/{policy_id}` | session | Delete a policy. Returns `204`. |
| POST | `/{policy_id}/apply` | session | Apply the policy (pushes a policy delta to targeted agents). |

### Plugins — `/api/v1/plugins`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | session | List installed/available plugins (`CursorPage[PluginResponse]`). |
| POST | `/{plugin_id}/install` | ADMIN, OPERATOR | Install a plugin (`list[PluginInstallationResponse]`). |
| POST | `/{plugin_id}/enable` | ADMIN, OPERATOR | Enable a plugin. |
| POST | `/{plugin_id}/disable` | ADMIN, OPERATOR | Disable a plugin. |
| DELETE | `/{plugin_id}` | ADMIN | Uninstall a plugin. |

### Playbooks — `/api/v1/playbooks` (requires `ansible-automation` plugin enabled)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | plugin-gated | List playbooks. |
| POST | `` | plugin-gated | Create a playbook. Returns `201`. |
| GET | `/{playbook_id}` | plugin-gated | Playbook detail. |
| PATCH | `/{playbook_id}` | plugin-gated | Update a playbook. |
| DELETE | `/{playbook_id}` | plugin-gated | Delete a playbook. Returns `204`. |
| POST | `/{playbook_id}/execute` | plugin-gated | Execute a playbook as a job. Returns `201` (`JobResponse`). |

### Playbook Templates — `/api/v1/playbook-templates` (requires `ansible-automation` plugin enabled)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | plugin-gated | List templates. |
| POST | `` | plugin-gated | Create a template. Returns `201`. |
| PATCH | `/{template_id}` | plugin-gated | Update a template. |
| DELETE | `/{template_id}` | plugin-gated | Delete a template. Returns `204`. |
| POST | `/{template_id}/launch` | plugin-gated | Launch a template as a job. Returns `201` (`JobResponse`). |
| GET | `/{template_id}/history` | plugin-gated | Prior job runs for the template (`list[JobResponse]`). |

### Ansible Roles — `/api/v1/ansible-roles` (requires `ansible-automation` plugin enabled)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | plugin-gated | List roles. |
| POST | `` | plugin-gated | Create a role. Returns `201`. |
| GET | `/{role_id}` | plugin-gated | Role detail. |
| PATCH | `/{role_id}` | plugin-gated | Update a role. |
| DELETE | `/{role_id}` | plugin-gated | Delete a role. Returns `204`. |

### Ansible Projects — `/api/v1/ansible-projects` (requires `ansible-automation` plugin enabled)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | plugin-gated | List projects. |
| POST | `` | plugin-gated | Create a project. Returns `201`. |
| GET | `/{project_id}` | plugin-gated | Project detail. |
| PATCH | `/{project_id}` | plugin-gated | Update a project. |
| DELETE | `/{project_id}` | plugin-gated | Delete a project. Returns `204`. |

### Alerts — `/api/v1/alerts`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | session | List alerts. |
| POST | `/{alert_id}/acknowledge` | ADMIN, OPERATOR | Acknowledge an alert. |
| POST | `/{alert_id}/resolve` | ADMIN, OPERATOR | Resolve an alert. |
| GET | `/rules` | session | List alert rules. |
| POST | `/rules` | ADMIN, OPERATOR | Create an alert rule. Returns `201`. |

### Admin — `/api/v1/admin`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/agent-config` | ADMIN, OPERATOR | Read agent default configuration. |
| PUT | `/agent-config` | ADMIN | Update agent default configuration. |
| GET | `/users` | ADMIN | List users. |
| POST | `/users` | ADMIN | Create a user. |
| POST | `/users/{user_id}/role` | ADMIN | Change a user's role. |
| DELETE | `/users/{user_id}` | ADMIN | Delete a user. |
| GET | `/settings` | ADMIN, OPERATOR | Read platform settings. |
| GET | `/settings/public` | session | Read public (non-sensitive) settings subset. |
| PUT | `/settings` | ADMIN | Update platform settings. |
| GET | `/audit` | ADMIN, AUDITOR | Read audit log. |

### Agent Install — `/api/v1/agent` and `/api/v1/agents`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/agent/packages` | session | List available agent package builds. |
| GET | `/agent/install.sh` | none (bootstrap script, plain text) | One-line install script served for `curl \| bash` style bootstrap. |
| POST | `/agent/enrollment-token` | ADMIN, OPERATOR | Issue an enrollment token for new agent registration. |
| GET | `/agent/download` | session | Download an agent package. |
| GET | `/agent/download-latest` | ADMIN, OPERATOR | Download the latest agent package build. |
| GET | `/agent/download-direct` | ADMIN, OPERATOR | Direct-download agent binary (JWT-authorized link, used by the dashboard's `/agents` download buttons). |

Note: `/agent/install.sh` has no `Depends(get_current_user)` — it is designed to be fetched by an unauthenticated shell one-liner during agent provisioning (enrollment itself is still gated by the enrollment token).

## Pagination

List endpoints that support cursor pagination return `CursorPage[T]` (`lokilinux/schemas/common.py`):

```json
{
  "items": [ /* array of T */ ],
  "next_cursor": "base64-opaque-cursor-or-null",
  "total": 1234
}
```

Request the next page with `?cursor={next_cursor}`. The cursor value is an opaque base64-encoded string (`encode_cursor`/`decode_cursor` in `common.py`); an invalid cursor returns `400 Invalid cursor`. `limit` on `/servers` is bounded to `1-100` (default `20`).

## Error responses

- `422` — request validation error. The global handler in `main.py` (`validation_error_handler`) returns:
  ```json
  { "detail": "Validation error", "errors": [ /* up to first 5 pydantic errors */ ] }
  ```
- `401` — missing/invalid/expired auth token.
- `403` — authenticated but insufficient role, or (on Ansible routers) the `ansible-automation` plugin is disabled.
- `503` — Better Auth session service unreachable (`{"detail": "Auth service unavailable"}` or `"Auth service unreachable: ..."`).
- Standard FastAPI `HTTPException` shape otherwise: `{"detail": "..."}`, optionally with a `code` field (`ErrorResponse` schema defines an optional `code: str | None`).

## Rate limits

No rate-limiting middleware or library (e.g. `slowapi`, `express-rate-limit` equivalent) was found in the backend dependencies or router code. <!-- VERIFY: whether rate limiting is enforced at a reverse proxy / API gateway layer in front of lokilinux-api -->

---

## gRPC API (Agent Communication)

### Transport

- Port: `50051` (env `GRPC_PORT`, default `50051`).
- **mTLS required** — `lokilinux/grpc_server.py::serve()` builds `grpc.ssl_server_credentials()` with `require_client_auth=True`, using:
  - Server cert/key: `SERVER_CERT_PATH` / `SERVER_KEY_PATH` (default `/etc/lokilinux/certs/server.crt` / `server.key`)
  - CA (to verify client certs): `CA_CERT_PATH` (default `/etc/lokilinux/certs/ca.crt`)
- Max message size: 16 MiB both directions (`grpc.max_recv_message_length` / `grpc.max_send_message_length`).

### Custom JSON codec

The server does **not** use standard protobuf wire serialization. It registers a `grpc.GenericRpcHandler` (`_AgentServiceHandler`) with custom (de)serializers:

- `request_deserializer=_from_json` — parses the incoming bytes with `json.loads(data, object_hook=lambda d: SimpleNamespace(**d))`, so nested objects arrive as `SimpleNamespace`, not `dict`.
- `response_serializer=_to_json` — `json.dumps(obj).encode()`.

This mirrors a matching JSON codec on the Go agent side, so both ends exchange newline-free JSON payloads over the gRPC stream framing rather than binary protobuf, despite `proto/lokilinux.proto` defining the message shapes for documentation/typing purposes.

### Service surface

`proto/lokilinux.proto` declares two services:

```proto
service AgentService {
  rpc HeartbeatStream(stream AgentHeartbeatRequest) returns (stream AgentHeartbeatResponse);
  rpc ReportMetrics(stream MetricsData) returns (MetricsAck);
  rpc SyncPolicy(PolicySyncRequest) returns (PolicyConfig);
}

service PlatformService {
  rpc ExecuteJobStream(JobRequest) returns (stream JobResult);
  rpc InstallPlugin(PluginInstallRequest) returns (PluginInstallResult);
}
```

**Only `AgentService.HeartbeatStream` is implemented** in `_AgentServiceHandler.service()` — the handler returns `None` (unimplemented) for any other method name, and `PlatformService` has no registered handler at all. `ReportMetrics`, `SyncPolicy`, `ExecuteJobStream`, and `InstallPlugin` exist in the proto contract but are not wired server-side.

### HeartbeatStream

Bidirectional stream, implemented in `lokilinux/api/grpc/agent_service.py::AgentServicer.HeartbeatStream`. For every `AgentHeartbeatRequest` received from the agent, the server yields one `AgentHeartbeatResponse`-shaped dict:

Request handling:
1. Resolves `ip_address` from the request, falling back to the gRPC peer address if omitted.
2. Calls `AgentService.update_heartbeat(agent_id, {...})` with `system_status`, `packages`, `packages_checksum`, `health`, `job_results`, `agent_version`, `recent_logs`, and log counters (`log_connections`, `log_informative`, `log_critical`).
3. Fetches pending jobs for the agent via `AgentService.get_pending_jobs(agent.id)`.

Response yielded per heartbeat:

```json
{
  "pending_jobs": [
    { "job_id": "uuid", "job_type": "PACKAGE_UPDATE", "parameters": {} }
  ]
}
```

Errors during processing are logged (`logger.error("HeartbeatStream error", exc_info=True)`) and swallowed — the stream continues rather than terminating on a single bad heartbeat.

### Message reference (from proto, informational)

`AgentHeartbeatRequest` fields (`proto/lokilinux.proto`): `agent_id`, `timestamp`, `system_status` (`SystemStatus`: hostname, os_family/distro/version, kernel_version, arch, cpu_count, memory, disks, boot_time, fqdn, system_users, network_interfaces, block_devices, listening_ports), `packages`, `services`, `repositories`, `custom_facts`, `vulnerabilities`, `health`, `pending_jobs`, `config_version`, `packages_checksum` (SHA-256, for delta-sync), `agent_version`, `recent_logs`, `log_connections`, `log_informative`, `log_critical`, `job_results`.

`AgentHeartbeatResponse` is a `oneof command`: `execute_job` (`JobRequest`), `update_policy` (`PolicyConfig`), `reboot_request` (string), `plugin_action` (string) — note the current server implementation only ever returns `pending_jobs`, not this oneof shape; treat the proto `oneof` as the target contract, not the current wire behavior.
