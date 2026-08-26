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

Rotație: `POST /api/v1/admin/kms/keys/job-signing/rotate` → versiune nouă ACTIVE, vechea VERIFY_ONLY. **Semnăturile istorice rămân verificabile** — envelope-urile poartă `key_version` (omit când =1 pentru compatibilitate cu agenții vechi).

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
