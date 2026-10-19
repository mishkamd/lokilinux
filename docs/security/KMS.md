# lokilinux-kms — Key Management & Signing

## Arhitectură

```
JobSigner (services/job_signing.py)      ← fața stabilă pentru tot pipeline-ul
   │
   ▼
SigningProvider (kms/provider.py)        ← Protocol: sign_message / public_key
   │
   ├─ FileSigningProvider (kms/file_provider.py)   ← development / fallback
   ├─ Vault provider                               ← viitor, aceeași interfață
   └─ HSM / PKCS#11                                ← viitor, aceeași interfață
```

## Lifecycle chei (KeyManager)

Layout versionat: `{LOKILINUX_KEYS_DIR}/{key_id}/v{N}.key` (0600) + `metadata.json`.

| Stare | Semnifică | Sign | Verify |
|---|---|---|---|
| ACTIVE | exact una; semnează tot ce e nou | ✓ | ✓ |
| VERIFY_ONLY | versiuni istorice după rotație | ✗ fail-closed | ✓ |
| RETIRED | compromis/retirată explicit | ✗ | ✗ (`unknown_signer` agent-side) |

Rotație: `POST /api/v1/admin/kms/keys/{key_id}/rotate` (ADMIN, `routers/admin.py`) → `KeyManager.rotate()` → versiune nouă ACTIVE, vechea VERIFY_ONLY. **Semnăturile istorice rămân verificabile** — envelope-urile poartă `key_version` (omit când =1 pentru compatibilitate cu agenții vechi). Necesită `LOKILINUX_KEYS_DIR` setat (409 altfel — layout-ul versionat e off). Prima rotație pe un deployment legacy migrează automat: `_get_signer()` (`services/job_envelope.py`) seedează v1 din fișierul static existent (`JOB_SIGNING_KEY_PATH`) înainte de a activa v2, deci pornirea versionării nu cere niciun downtime sau resemnare. Auditat (`kms.key.rotated`, `from_version`/`to_version`) și numărat (`kms_rotation_total`).

## Configurație

```yaml
# env-driven v1:
JOB_SIGNING_KEY_PATH=/etc/lokilinux/certs/job_signing.key     # legacy single key = v1
LOKILINUX_KEYS_DIR=/var/lib/lokilinux/keys                    # layout versionat (opțional)
KMS_PROVIDER=file                                             # vault/hsm = NotImplementedError explicit
ALLOW_FILE_KEYS_IN_PRODUCTION=true                            # necesar în profilul production
```

## Failure model (fail-closed)

- provider indisponibil / timeout → `ProviderUnavailable` → semnare eșuează, jobul NU pleacă nesemnat
- cheie necunoscută/retrasă la verificare → agent respinge cu `unknown_signer`
- niciodată fallback automat la altă cheie sau la nesemnat când `JOB_SIGNING_REQUIRED=true`

## Secrete

Erorile KMS conțin doar `key_id`, `version`, `reason`. Materialul privat nu ajunge în logs, răspunsuri API, metrics sau erori (redacția de loguri din agent e al doilea strat).

## Metrics & audit

- `kms_sign_success_total` / `kms_sign_failure_total{reason}` / `kms_provider_latency_seconds` — incrementate în `JobSigner._provider_sign()`, singurul punct prin care trec `sign()`, `sign_message()` și `sign_approval_claim()`.
- `kms_rotation_total` — incrementat de endpoint-ul de rotație.
- Audit: `kms.key.rotated` (`resource_type=kms_key`, `changes={from_version,to_version}`) la fiecare rotație reușită.

## Ce rămâne de implementat

Planul [`2026-08-25-kms-and-hardening-completion.md`](../superpowers/plans/2026-08-25-kms-and-hardening-completion.md) marca întreaga Fază F ca implementată printr-un singur commit (`d182bf7`), dar acoperea doar F1 (provider+`KeyManager`) și F2 (`JobSigner` versionat). F3 (rotație operațională, audit, metrics) a fost completată ulterior — endpoint, wiring `_get_signer()`→`KeyManager` (altfel rotația nu ajungea niciodată la semnatorul care rulează efectiv), metrics și audit, toate testate (`test_kms.py`, `test_job_signing.py`, `test_job_envelope.py::test_rotation_reaches_running_signer`, `test_admin_kms_router.py`).

Rotație operațională end-to-end (endpoint-uri stage/status/activate/retire,
`GET /agent/signing-keys` versionat consumat de ambele installere, script +
runbook) — vezi [`JOB_SIGNING_ROTATION.md`](JOB_SIGNING_ROTATION.md).

Rămâne deschis:

- Vault/HSM rămân deliberat `NotImplementedError` în `get_provider()` — interfața (`SigningProvider`) e stabilă, dar implementarea concretă e viitor, nu un gap de urgență.
- **Fără push runtime de chei** — agentul citește `signing_pub_keys` doar la startup; o rotație ajunge la agenți vii doar prin re-install/Ansible, documentat explicit ca pas manual în runbook. Un canal de push ar cere RPC nou + release de agent — nu e planificat.
