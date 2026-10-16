# Rotația cheii de job-signing — fără downtime de joburi semnate

Runbook pentru rotația cheii Ed25519 care semnează joburile privilegiate,
conform `scripts/security/rotate-job-signing-key.sh`. Simetric cu
`CERTIFICATE_ROTATION.md`, dar pentru `KeyManager`/`SigningProvider`
(`docs/security/KMS.md`) în loc de CA mTLS.

## Premise

- Necesită `LOKILINUX_KEYS_DIR` configurat pe `lokilinux-api` — fără layout
  versionat, endpoint-urile `/admin/kms/keys/...` răspund 409 (același guard
  ca la `rotate`-ul atomic existent).
- Agentul citește cheile publice **doar la startup**, din
  `security.signing_pub_keys` (`agent.yaml`) — **nu există push runtime**.
  O cheie nouă ajunge la un agent viu doar printr-un re-run al installerului
  sau al layer-ului Ansible existent, nu prin rotația din sine.
- `GET /api/v1/agent/signing-keys` servește harta versionată (ACTIVE +
  VERIFY_ONLY; RETIRED **niciodată**) — sursa pe care installerul o scrie în
  `signing_pub_keys`.
- Token: pașii care schimbă stare cer `ADMIN_TOKEN` (JWT Bearer, rol ADMIN —
  obținut din sesiunea frontend-ului, `localStorage`/dev-tools după login).

## De ce nu endpoint-ul `rotate` existent

`POST /admin/kms/keys/{id}/rotate` face `create()`+`activate()` **atomic** —
util la bootstrap (nimeni nu semnează încă nimic), periculos pe o flotă vie:
imediat după apel, control-plane-ul semnează cu versiunea nouă, dar agenții
încă nu o cunosc → toate joburile privilegiate cad cu `unknown_signer` până
la următorul re-enrollment. Rotația live are nevoie de pașii separați de mai
jos.

## Pași

| # | Pas | Comandă |
|---|---|---|
| 1 | Stage versiune nouă (VERIFY_ONLY, nu semnează încă nimic) | `ADMIN_TOKEN=... rotate-job-signing-key.sh stage` |
| 2 | Distribuie cheia publică nouă pe flotă **înainte** de activare | Re-roll `install.sh` pe agenți (citește `GET /agent/signing-keys`, scrie `signing_pub_keys` cu ambele versiuni) — via Ansible sau manual, host cu host |
| 3 | Verifică ce a primit fiecare agent | `cat /etc/lokilinux/agent.yaml` pe un eșantion — trebuie să conțină ambele versiuni sub `security.signing_pub_keys` |
| 4 | Activează versiunea nouă (semnarea trece pe ea) | `ADMIN_TOKEN=... rotate-job-signing-key.sh activate --confirm` |
| 5 | Smoke test pe un job semnat real | `scripts/security/e2e_signed_job.sh` sau dispatch manual către un agent viu |
| 6 | Verificare fleet | `ADMIN_TOKEN=... rotate-job-signing-key.sh status` — confirmă ACTIVE pe versiunea nouă; niciun agent cu joburi respinse (`unknown_signer` în logs/metrics `agent_rejected_jobs_total`) |
| 7 | Retire versiunea veche — **doar** după ce TOȚI agenții sunt pe versiunea nouă | `ADMIN_TOKEN=... rotate-job-signing-key.sh retire <versiune-veche> --confirm` |

## Invariante

- **Niciodată** retire înaintea distribuției — un agent care încă citește
  varianta veche (nu a fost re-instalat) e blocat imediat: toate joburile
  lui privilegiate refuzate cu `unknown_signer`.
- Rotația nu șterge material vechi la `retire` — versiunea rămâne pe disc,
  doar starea trece la `RETIRED` (verificarea e refuzată, semnătura fizică
  rămâne recuperabilă pentru audit istoric).
- `activate` promovează întotdeauna cea mai recentă versiune `VERIFY_ONLY` —
  dacă există mai multe versiuni staged simultan (rotații suprapuse),
  verifică `status` înainte de a confirma.
- Audit: fiecare pas emite `kms.key.staged` / `kms.key.activated` /
  `kms.key.retired` (`resource_type=kms_key`) — vezi `/admin/audit-log`.

## Ce NU acoperă acest runbook

- **Push runtime de chei** — n-are canal azi; agentul le citește doar la
  startup. Rămâne pas manual (re-install / Ansible) pentru fiecare rotație,
  documentat explicit la pasul 2, nu ceva ce scriptul poate automatiza fără
  un RPC nou + release de agent.
- Vault/HSM ca provider — `get_provider()` respinge orice altceva decât
  `file` cu `NotImplementedError` deliberat.

## Status testare

**NOT TESTED live pe flotă** — endpoint-urile și scriptul sunt validate
unitar/integration (`test_kms.py`, `test_admin_kms_router.py`,
`test_agent_signing_keys.py`) și randarea YAML a installerelor a fost
verificată manual, dar secvența completă n-a rulat încă pe agenți reali.
Urmează același tipar ca rotația CA din `CERTIFICATE_ROTATION.md` — rulați
mai întâi pe un singur agent de test înainte de flota completă.
