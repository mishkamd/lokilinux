# Security Hardening — Finalization Plan

> **STATUS (2026-08-25): COMPLET.** `06a3535` broker telemetry+flip · `2669e50` remediation runners · `d7ca41a` CRL re-enroll · `22248fd` bundle guard · `bbd39f5` docs+E2E.
> **E2E LIVE: 8/8 PASS** pe stack real (`scripts/security/e2e_signed_job.sh` vs lokilinux-api:0.3.0 rebuild — signing-key endpoints, revocation gating 401, metrics 9090). Deploy efectuat: rebuild api image (prometheus-client 0.21.1), migrate alembic 030, cheie signing provizionată în volumul certs, ClickHouse network-user fix pentru stack-ul local.

> **For agentic workers:** superpowers:executing-plans. Checkbox tracking.

**Goal:** Închiderea ultimelor gap-uri: telemetrie prin broker (deblochează non-root), COMPLIANCE_REMEDIATE prin broker, CRL la re-enroll, validare operațională (E2E local condiționat + distro runbook).

**Decizii:** E2E local încercat (NOT TESTED dacă mediul nu cooperează) · Vault/HSM rămâne stub · flip non-root doar cu broker confirmat.

## Faza 1 — Telemetrie prin broker
- [ ] 1.1 `modules.CheckPackageUpdates(ctx, jobID)` export wrapper
- [ ] 1.2 Broker op `package.check_updates`
- [ ] 1.3 Telemetry routing prin broker când configurat
- [ ] 1.4 Installer flip: broker ⇒ User=loki-agent

## Faza 2 — Remediation prin broker
- [ ] 2.1 Broker-backed ActionRunners (shell/ansible/python → ops existente)
- [ ] 2.2 Ștergere `[broker_gap]` din broker_routing.go
- [ ] 2.3 Test dry-run fake broker

## Faza 3 — CRL la re-enroll
- [ ] 3.1 `previous_serial` opțional în /agents/register + assert_not_revoked + docs

## Faza 4 — Validare operațională
- [ ] 4.1 E2E local condiționat (`scripts/security/e2e_signed_job.sh` + compose up)
- [ ] 4.2 `docs/security/DISTRO_RUNBOOK.md` dedicat
- [ ] 4.3 Rollout checklist în EXECUTION_MODEL.md

## Faza 5 — Docs + raport final
- [ ] ARCHITECTURE pointer + raport onest IMPLEMENTED/TESTED/NOT TESTED

Commituri atomice per task-grup.
