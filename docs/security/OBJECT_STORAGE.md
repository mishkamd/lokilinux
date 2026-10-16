# Object Storage — RustFS / S3

## Arhitectură

```
Business logic (routers, services)
   │
   ▼
StorageService (services/storage_service.py)   ← singurul punct de intrare
   │  hash SHA-256, validare mărime/categorie, audit log
   ▼
ObjectStorage (object_storage.py)               ← wrapper boto3, vendor-neutru
   │
   ▼
RustFS (self-hosted, S3-compatible)             ← implicit; AWS S3/R2/Wasabi = config change
```

Niciun modul de business logic nu importă `boto3` direct — totul trece prin `StorageService`. Swap-ul
de provider e `S3_ENDPOINT_URL` + `S3_ACCESS_KEY`/`S3_SECRET_KEY`, nu o schimbare de cod.

## Credentials

`RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY` (container) și `S3_ACCESS_KEY`/`S3_SECRET_KEY` (aplicație) sunt
aceeași pereche — generată de utilizator la `cp .env.example .env`, niciodată valoarea implicită
`rustfsadmin` documentată de RustFS ca nesigură. Nu există rotație automată; rotația e manuală (schimbi
`.env`, `docker compose up -d rustfs lokilinux-api`) — nu există încă un endpoint de rotație ca la
[KMS](KMS.md).

Bucket-ul (`lokilinux`, implicit) e privat — nu există policy public, nu există listare anonimă.
`ensure_bucket()` rulează la fiecare pornire a `lokilinux-api` (head-then-create, idempotent).

## Rețea

RustFS stă exclusiv pe `app-net` (`internal: true`) — niciun port publicat în producție.
`docker-compose.dev.yml` publică `9000` (S3 API) și `9001` (consolă) doar pentru inspecție locală;
consola nu trebuie niciodată expusă public.

## Presigned URLs — dezactivate implicit

Pentru că RustFS e pe o rețea internă, un URL presemnat către `http://rustfs:9000/...` nu e accesibil
dintr-un browser. Deci:

- **Download implicit**: `GET /storage/objects/{id}/download` întoarce un `StreamingResponse` — API-ul
  citește din RustFS și retransmite byte-urile, funcționează întotdeauna.
- **Presign opțional**: `?presign=true` întoarce un URL doar dacă `S3_PUBLIC_ENDPOINT_URL` e setat —
  adică doar când S3 e cu adevărat accesibil dintr-un browser (AWS S3, Cloudflare R2, Wasabi, sau RustFS
  în spatele unui reverse proxy public). Altfel → `409` cu motivul explicit, nu un URL mort.

Ca să activezi presigned URLs cu RustFS self-hosted, pune un reverse proxy TLS în fața portului 9000 și
setează `S3_PUBLIC_ENDPOINT_URL` la acel host public.

## Validare la upload

- `sanitize_filename()` — strip path components, whitelist caractere, lungime maximă. Numele original
  nu ajunge niciodată neschimbat în `object_key`.
- `validate_key()` — respinge `..`, path-uri absolute, NUL byte, pe fiecare operație (put/get/delete/head),
  nu doar la upload.
- `s3_max_upload_bytes` (implicit 500MB) — impus în `StorageService.store_stream` în timp ce se
  streamează, nu după ce fișierul e deja complet încărcat.
- Fișierele mari (>8MB, `s3_multipart_threshold_bytes`) folosesc multipart automat prin
  `boto3.s3.transfer.TransferConfig` — nicio implementare manuală de multipart.

## Audit

Fiecare upload/download/delete trece prin `AuditService` (`storage.uploaded` / `.deleted`,
`resource_type=storage_object`) — vezi tiparul din `routers/admin.py`. Descărcările nu sunt auditate
individual (ar fi zgomotos pentru path-ul de citire); upload și delete da.

## Ce NU e stocat în S3 — și de ce

| Date | De ce rămân în Postgres |
|---|---|
| Chei de semnare (job signing, policy signing), CA/certificate | Secret material cu propriul model de rotație/acces ([KMS.md](KMS.md)) — nu e un artifact. |
| `inventory_blobs` | Content-addressable, deduplicat fleet-wide, în calea directă de citire a snapshot-urilor — un round-trip S3 acolo ar fi o regresie de performanță. |

Playbook Ansible, rol și workflow YAML **au fost migrate** în S3 (vezi mai jos) — inclusiv calea de
dispatch a job-urilor din `WorkflowRunnerWorker`/`WorkflowSchedulerWorker`/`IncidentWorker`, care acum
depind de `storage` la fel ca orice alt worker. Aceasta a fost o decizie explicită, luată după ce
riscul (o dependență S3 nouă în calea de execuție, pentru documente-sursă mici) a fost semnalat și
acceptat — vezi secțiunea următoare pentru ce s-a schimbat concret.

## Dual-read (migrare fără backfill)

Rândurile scrise înainte de acest layer (`compliance_reports.body` BYTEA) rămân neschimbate — `body`
e nullable, nu s-a rulat niciun backfill. `storage_object_id` e `NULL` pe rândurile vechi;
`download_report` citește `body` direct când `storage_object_id` lipsește, altfel proxy prin S3. Orice
migrare viitoare de tip file-shaped urmează același tipar: coloană FK nulabilă + citire duală, nu un
job de backfill.

## Playbook Ansible / rol / workflow YAML — conținut executabil în S3

Spre deosebire de rapoarte/datastream-uri (fișiere generate/importate, fără rol în dispatch), acest
conținut alimentează direct execuția: `PlaybookService.execute_playbook` citește conținutul (din S3
sau, pentru rânduri vechi, din coloana legacy) și îl inserează în `Job.parameters` înainte de semnarea
Ed25519 a envelope-ului — semnătura acoperă tot ce ajunge la agent, exact ca înainte. Snapshot-ul rămâne
în Postgres (JSONB pe `jobs`), nu în S3 — doar sursa DE UNDE se citește conținutul la momentul creării
job-ului s-a mutat.

Asta a introdus o dependență nouă pe `storage` în trei worker-e de fundal (`WorkflowRunnerWorker`,
`WorkflowSchedulerWorker`, `IncidentWorker` — pentru runbook-uri AUTO), plus în routerele
`playbooks.py`/`ansible_roles.py`/`workflows.py`/`policies.py` (migrarea unei Policy la Workflow).
Fiecare a primit `storage: ObjectStorage` prin `Depends(get_storage)` (routere) sau prin constructor
(worker-e, cablate în `main.py`'s lifespan) — același tipar deja folosit pentru `nats`.

Listele (`GET /playbooks`, `GET /ansible-roles`) omit deliberat conținutul complet — un `PlaybookListItem`/
`AnsibleRoleListItem` separat de modelul de detaliu, ca să nu declanșeze un read S3 per rând la fiecare
încărcare de pagină. `GET /workflows/{id}/versions` rămâne cu YAML complet per item (domeniul e mărginit
la versiunile UNUI workflow, nu tot fleet-ul), la fel ca înainte.

## Pachete agent

Binarele agent (`.tar.gz`/`.deb`/`.rpm`, ~51MB per release) sunt în S3 sub chei deterministe
(`system/agent-packages/<versiune>/<filename>`) — NU prin tabela `storage_objects` (nimic de urmărit
per-upload, o versiune suprascrie mereu aceeași cheie). `agent_install.py` verifică existența cu
`storage.exists()` și descarcă prin `StreamingResponse`; scriptul de release
(`.claude/skills/ship-changes/scripts/release.sh`) le urcă după `make agent-package`, direct din
containerul `lokilinux-api` (singurul cu credentials S3), nu de pe host — RustFS e internal-only.
Bind mount-ul `./agent/bin:/opt/lokilinux/packages:ro` și mount-ul `/downloads` au fost eliminate.

## Ce rămâne de implementat

Attachments pentru incidente/diagnostic bundles rămân follow-up neînceput — layerul central le poate
primi oricând, fără nicio schimbare de arhitectură.
