# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Internal IT/DevOps teams — a single sysadmin or a small ops team administering their own company's fleet of Linux servers. Self-hosted, single-tenant (docker-compose deploy, one organization's infrastructure, no cross-tenant isolation in the schema). They interact with LokiLinux to keep servers patched, track and remediate CVEs, watch compliance drift, and run fleet-wide jobs (package updates, Ansible playbooks, custom commands) without SSHing into each host by hand.

## Product Purpose

LokiLinux is an enterprise Linux fleet management platform. A lightweight Go agent installed on each managed server reports system state, installed packages, and known vulnerabilities on a heartbeat; the platform aggregates this across the fleet into one dashboard for patch management, CVE tracking, compliance-drift detection, and remediation — plus a job engine to push package updates, Ansible playbooks, and custom commands out to targeted servers.

## Positioning

Unlike Ansible Tower/AWX (SSH push, orchestration-first) or Foreman/Katello and Red Hat Satellite (heavier provisioning/lifecycle platforms), LokiLinux's agent pulls its instructions on a lightweight heartbeat (gRPC, ~60s interval) rather than requiring an SSH-reachable, orchestrator-driven push model — simpler to install and reason about per-host, at the cost of heartbeat-interval latency (a known, documented tradeoff, not a defect). Its second differentiator is unifying three concerns competitors keep separate: vulnerability/CVE tracking, compliance drift, and patch remediation live in one data model and one dashboard instead of three tools.

## Operating Context

Admins manage a fleet of Linux servers across distro families — RHEL, Rocky, Oracle Linux, Debian, Ubuntu — through a single web dashboard (today's live fleet evidence happens to be Rocky hosts; the product direction is cross-distro, see Capabilities and Constraints). Core workflows: enroll a server (agent install), watch its heartbeat-reported health/packages/vulnerabilities, review the CVE catalog and compliance-drift findings across the fleet, launch and monitor jobs (package updates, Ansible playbooks, custom shell commands) against one or many servers, and review audit/job history. The platform itself runs as a docker-compose stack (Postgres/TimescaleDB, Redis, NATS, FastAPI REST + gRPC backend, a Go compliance microservice, Nuxt frontend).

## Capabilities and Constraints

- Agent-based, heartbeat-pull architecture (Go agent, ~60s default interval, gRPC over mTLS) — not SSH push.
- Confirmed product direction: **cross-distro**, not RHEL/Rocky-only — LokiLinux must manage RHEL, Rocky, Oracle Linux, Debian, and Ubuntu alike. Current implementation gap (not a product boundary): CVE cross-referencing is dnf/yum-only today (`agent/internal/modules/package_manager.go`); apt/zypper paths exist for package listing but have no CVE source wired up yet. Closing this gap (apt/dpkg CVE data for Debian/Ubuntu, zypper for SUSE if in scope) is a real backlog item, not a design decision to make here.
- Single-tenant per deployment; no multi-org/multi-tenant isolation exists in the data model today.
- Job dispatch and result delivery are bounded by the heartbeat interval (documented, real UX latency — not something the UI should hide, but something it should communicate honestly).
- Compliance domain collection is a generic, schema-free channel (new domains need no backend changes); vulnerability/CVE data model is host-scoped only today (no container/image-scan target yet).

## Brand Commitments

- Name and logo are final: **LokiLinux**, Norse-helmet mark, no rebrand in scope.
- Tagline in use: "Enterprise Linux Fleet Management" / "Fleet Management Platform".
- Visual identity is locked, not just current state: the "Precision Terminal" aesthetic (dark, near-black canvas; forest-green primary; monospace-driven data typography; command-center density) is a confirmed brand commitment for all future design work, not a stage to redesign away from.

## Evidence on Hand

Live, running implementation is the evidence — no separate marketing assets or case studies exist. Real screenshots taken this session show the working dashboard, vulnerability management module, job execution UI, and server detail views against live (non-fabricated) fleet data.

## Product Principles

1. Heartbeat latency is a known tradeoff, not a bug to hide — the UI should surface "waiting for the agent" honestly rather than pretend real-time when it isn't.
2. One dashboard, three concerns unified: vulnerabilities, compliance drift, and patch remediation stay connected, not siloed into separate tools/views.
3. Agent-side simplicity over orchestration weight — features should prefer the lightweight pull model over reintroducing SSH/push complexity.
4. Density and legibility over decoration — this is an ops tool used daily by admins scanning for problems, not a marketing surface.
