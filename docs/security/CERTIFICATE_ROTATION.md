# CA Rotation — fără reinstalarea agentului

Runbook pentru înlocuirea CA-ului mTLS cu dual-trust, conform `scripts/security/rotate-ca.sh`.

> **EXECUTAT (2026-08-27):** rotația a fost rulată live pe flota de referință (2 agenți). Ordinea validată: generate → bundle → server pe bundle → agenți pe bundle (0.38.0 installer/manual) → server cert re-sign sub CA_new → promote CA_new (ca.crt + ca.key signer) → signed-job smoke → E2E 8/8. Agent certs rămân CA_old-signed până la renew-ul automat (<7d TTL) — păstrați bundle-ul dual pe agenți până atunci. `retire-old` din script ASUMĂ certs re-emise; nu-l rula după un promote care păstrează certs vechi active.

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

## Ce face codul cu certificatele agenților

Verificat în `scripts/security/rotate-ca.sh`, `agent/internal/agent/cert_renewal.go`, `backend/lokilinux/services/ca_signer_service.py` și `backend/lokilinux/grpc_server.py`.

- **Certificatele CA_old rămân în uz până la renew.** Agentul reînnoiește doar când certificatul are mai puțin de 7 zile până la expirare (`certRenewalThreshold`). TTL-ul implicit este 30 de zile (`agent_cert_ttl_days`). Renew-ul este semnat de `ca-signer`, care încarcă `CA_KEY_PATH` la pornire: până la repornirea signer-ului cu cheia CA_new, renew-ul produce tot certificate CA_old. Renew-ul scrie doar cheia și certificatul agentului; fișierul CA al agentului nu se schimbă.
- **`retire-old` schimbă doar fișierele CA.** Copiază `ca.crt` în `ca-retired-<dată>.crt`, pune `ca-new.crt` în `ca.crt` și rescrie `ca-bundle.crt` cu un singur certificat. Nu verifică dacă agenții sunt pe CA_new (afișează doar gate-ul manual), nu revocă serialele (afișează endpoint-ul), nu mută `ca.key` sau `ca-new.key` și nu repornește serviciile. Mesajul scriptului despre „arhivarea” cheii CA_old nu corespunde codului: nicio cheie nu este mutată sau ștearsă.
- **Efectul asupra trustului apare la repornire.** Serverul gRPC citește `CA_CERT_PATH` la pornire și îl folosește ca `root_certificates` cu `require_client_auth=True`. După repornirea cu un singur CA, un certificat semnat doar de CA_old nu mai trece handshake-ul mTLS. Agentul respectiv nu se poate conecta, iar renew-ul (care trece prin același mTLS) nu ajunge la server. Scriptul nu tratează acest caz.
- **Rollback manual.** Scriptul nu are comandă de rollback. Mesajul său cere restaurarea din `ca-retired-*.crt` și regenerarea bundle-ului dual.
- **Înregistrarea nouă primește `ca.crt`, nu bundle-ul.** `POST /agents/register` returnează `ca_cert` citit din `agent_cert_dir/ca.crt` (`backend/lokilinux/api/v1/routers/agent_install.py`, `_generate_agent_cert`), iar `scripts/install-agent.sh` îl scrie în `ca.crt`. `bundle` nu modifică `ca.crt`, deci o instalare nouă în fereastra dual-trust primește doar CA_old până când `ca.crt` este înlocuit. Premisa „instalatorul scrie bundle-ul” de mai sus nu se confirmă pentru această cale.

## Status testare

**NOT TESTED live** — secvența a fost validată structural (script idempotent, bundle generat, grpc acceptă PEM multi-cert) dar nu pe o flotă reală Ubuntu/Rocky. Vezi `docs/security/DISTRO_RUNBOOK.md`.
