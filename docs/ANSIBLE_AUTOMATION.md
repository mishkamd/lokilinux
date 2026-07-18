# Ansible Automation

AWX-like automation layer, gated behind the `ansible-automation` plugin (see [PLUGINS](#plugin-gating) below). Adds playbook-based configuration management on top of the existing patch-management job pipeline.

## Entities

| Entity | Table | Purpose |
|--------|-------|---------|
| **Project** | `ansible_projects` | Groups playbooks. `default_agent_ids` is the project's inventory — the live fleet already *is* the inventory, so no static hosts files exist. |
| **Role** | `ansible_roles` | Reusable file set stored as a JSONB `path → content` map (e.g. `{"tasks/main.yml": "...", "defaults/main.yml": "..."}`). No filesystem storage layer — files materialize under `<tmpdir>/roles/<name>/` on the agent at execution time, where `ansible-playbook` resolves them automatically. Versioned (`version` column, bumped on edit); can be `is_enabled` toggled. |
| **Playbook** | `playbooks` | Raw YAML in `content`. Versioned on every edit. Optionally scoped to a `project_id`, references `role_ids`. `generated_by` is a seam for a future AI-assist feature (`"user"` today; no AI code exists yet). |
| **Job Template** | `playbook_templates` | Saved `(playbook_id, agent_ids, extra_vars)` combo — AWX's "Job Template". References the playbook by id and always runs its *current* content at launch — no snapshotting, same behavior as a direct execute. |

## Execution model

Execution runs **locally on each target agent** (`ansible-playbook --connection=local`), not via SSH from a control node — the agent already holds an outbound mTLS channel to the control plane, so no inbound SSH exposure is needed on managed hosts. "Target servers" are agents already registered in the fleet, selected the same way as regular patch jobs.

`PlaybookService.execute_playbook` creates a `Job` row (same `jobs` table and state machine as patch/remediation jobs — `QUEUED → SCHEDULED → PENDING → RUNNING → COMPLETED`/`FAILED`/`TIMEOUT`/`CANCELLED`), which the agent picks up via its normal heartbeat response. The agent's `ansible_executor` module materializes the playbook (and any linked roles) into a temp dir and runs it locally.

## Plugin gating

Every Ansible route requires the `ansible-automation` row in the `plugins` table to have `is_enabled = true` (`require_plugin_enabled()` dependency in each router). Disabling the plugin from `/plugins` immediately locks out playbook/project/role/template management and execution with `403` — same on/off contract as any other installable plugin (`PENDING_INSTALL → INSTALLING → INSTALLED → ENABLED`, see plugin lifecycle in the README).

## API surface

| Prefix | Router file |
|--------|-------------|
| `/api/v1/ansible-projects` | `ansible_projects.py` |
| `/api/v1/ansible-roles` | `ansible_roles.py` |
| `/api/v1/playbooks` | `playbooks.py` |
| `/api/v1/playbook-templates` | `playbook_templates.py` |

## Frontend

`/automation/ansible/projects`, `/automation/ansible/roles[/:id]`, `/automation/ansible/playbooks[/:id]`, `/automation/ansible/templates`.
