# CA Rotation — fără reinstalarea agentului

Runbook pentru înlocuirea CA-ului mTLS cu dual-trust, conform `scripts/security/rotate-ca.sh`.

## Premise

- Agentul verifică serverul prin `ca_path` din `/etc/lokilinux/agent.yaml`. Installerul scrie **bundle-ul** (`ca-bundle.crt` = CA_old + CA_new), deci un agent instalat/actualizat în timpul ferestrei de dual-trust are deja ambele CA-uri.
- Serverul validează clienții împotriva `CA_CERT_PATH` (grpc acceptă bundle multi-PEM nativ).
- Serialul certificatului fiecărui agent poate fi revocat individual: `POST /api/v1/admin/certificates/{serial}/revoke`.

## Pași

| # | Pas | Comandă / acțiune |
|---|---|---|
| 1 | Generează CA_new | `rotate-ca.sh generate /etc/lokilinux/certs` |
| 2 | Bundle dual-trust | `rotate-ca.sh bundle` → repornește `lokilinux-api` + `lokilinux-grpc` cu `CA_CERT_PATH=.../ca-bundle.crt` |
| 3 | Distribuie trust material | Re-roll installer (`install.sh`) pe agenți noi; agenți existenți: bundle-ul ajunge la următorul update agent SAU manual: scp `ca-bundle.crt` → `/etc/lokilinux/certs/ca.crt` + `systemctl restart lokilinux-agent` |
| 4 | Rotește certificatele | Emite certuri noi semnate de CA_new (re-enroll per agent sau bulk script); agentul primește cert+key noi fără reinstalare binarului |
| 5 | Reconectare | Agentul se reconectează automat (`Restart=always`, backoff existent) |
| 6 | Verificare fleet | `rotate-ca.sh verify-fleet <N>` — TOȚI agenții HEALTHY în dashboard înainte de a continua |
| 7 | Revocă certificatele vechi | Pentru fiecare agent rămas pe CA_old: `POST /admin/certificates/{serial}/revoke` |
| 8 | Elimină CA_old | `rotate-ca.sh retire-old` — arhivează `ca-retired-<dată>.crt`, promovează CA_new, bundle → single-CA |
| 9 | Rollback | În fereastra de valabilitate: restaurează arhiva + regenerează bundle-ul dual (dual trust din nou) |

## Invariante

- NICIODATĂ nu ștergem materialul CA_old la pasul 8 — arhivat pentru verificare istorică.
- Dacă Redis (revocare) e picat și `fail_closed=true`, conexiunile noi sunt respinse până se rezolvă — rotația nu ocolește CRL-lite.
- Agenții care nu au primit bundle-ul ÎNCĂ continuă să funcționeze atât timp cât serverul e în dual-trust.

## Status testare

**NOT TESTED live** — secvența a fost validată structural (script idempotent, bundle generat, grpc acceptă PEM multi-cert) dar nu pe o flotă reală Ubuntu/Rocky. Vezi `docs/security/DISTRO_RUNBOOK.md`.
