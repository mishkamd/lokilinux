# 11 — Sistemul de plugin-uri

> Documentație generată din cod la commit `7415631` (v0.5.0), octombrie 2026. Cifrele de mai jos sunt verificate pe cod la acest commit.
>
> **Publicat ca document de echipă în Linear** (Documents → LokiLinux, vizibil în afara
> proiectului): https://linear.app/mishkamd/document/11-sistem-de-plugin-uri-ed4240f2bb69
> Celelalte documente de modul sunt atașate la proiectul LokiLinux (P-MIS-1); indexul e
> [00 — Index documentație module](00-index.md).

## Rol

Sistemul de plugin-uri e **calea prin care capabilități noi intră în LokiLinux fără fork-ul platformei**. Un plugin e o unitate cu `name` unic în DB, cu un ciclu de viață controlat de server (`PENDING_INSTALL → INSTALLING → INSTALLED → ENABLED`, plus `DISABLED` / `INSTALLING_FAILED` / `ERROR`), care poate fi:

- **de tip `control-plane`** — rulează în interiorul platformei (ex. `ansible-automation`), se activează printr-un rând în `plugins` și **deblochează rute REST** prin `require_plugin_enabled()`;
- **de tip `agent`** — e un artefact descărcat de agent pe fiecare host vizat, cu verificare SHA-256 + semnătură Ed25519;
- **de tip `ui` / `notification`** — tipuri declarate în model, dar fără runtime implementat azi.

**Ce NU e sistemul de plugin-uri:** colectoarele de compliance. Alea sunt compilate în binarul agentului (`agent/internal/compliance/`) și au alt model de încredere și alt lifecycle — vezi [docs/compliance/03-AGENT-PLUGIN-SDK.md](../compliance/03-AGENT-PLUGIN-SDK.md) §1. Nu confunda.

## Starea reală a sistemului (citit asta înainte să scrii un plugin)

Sistemul de plugin-uri e **partially implemented**. Ce e real:

| Piesă | Stare | Unde |
|---|---|---|
| Model + tabele `plugins` / `plugin_installations` | ✅ real | `backend/lokilinux/models/plugin.py` |
| CRUD REST: list / install / enable / disable | ✅ real | `backend/lokilinux/api/v1/routers/plugins.py` |
| Job type `PLUGIN_INSTALL` + signed envelope | ✅ real | `services/job_service.py`, `services/job_envelope.py` |
| Download + SHA-256 + Ed25519 pe agent | ✅ real | `agent/internal/modules/plugin_installer.go` |
| Gating pe `require_plugin_enabled()` | ✅ real | `api/v1/routers/playbooks.py:40-63` |
| Runtime de **execuție** a plugin-ului pe agent | ❌ **nu există** | agentul descarcă și plasează fișierul, dar nu îl execută |
| Loader Python/Go (`docs/arhitecture/plugin-sdk/`) | ⚠️ **design only** | SDK-ul e un design doc; niciun loader în cod |
| Marketplace / sync din remote | ❌ **nu există** | `settings.plugins.marketplace_url` e storage-only (`settings_schema.py:9-11`) |
| `PLUGINS_ENABLED`, `PLUGINS_DIR`, sandbox limits | ❌ **nu citite** | în `.env.example` și în `docs/arhitecture/`, dar niciun cod nu le citește |

Concluzie: azi poți **scrie, înregistra, instala (pe flotă) și activa** un plugin, și îl poți folosi ca **feature flag pe rute REST**. Nu poți încă scrie un plugin care rulează cod arbitrar pe agent — installerul e un transport de artefacte, nu un runtime.

## Cum arată un plugin în DB

Tabela `plugins` (`backend/lokilinux/models/plugin.py:27-69`):

| Coloană | Tip | Rol |
|---|---|---|
| `name` | `String(255)` unique | cheie logică; `ansible-automation` e referința canonică |
| `display_name`, `description`, `author`, `icon_url`, `documentation_url` | — | metadata afișate în UI (`frontend/pages/plugins/index.vue`) |
| `version` | `String(50)` | versiunea artefactului |
| `plugin_type` | `String(50)` | `control-plane` / `agent` / `ui` / `notification` |
| `min_platform_version` / `max_platform_version` | `String(50)` | fereastra de compatibilitate |
| `source_url` | `String(512)` | de unde agentul descarcă artefactul (doar pentru `plugin_type='agent'`) |
| `manifest` | `JSONB` | metadata liberă (`entrypoint`, `permissions`, …) |
| `checksum` | `String(64)` | SHA-256 hex al artefactului |
| `is_enabled` / `is_installed` | `Boolean` | stările efectoase |
| `installation_status` | enum `pluginstatus` | starea de mai sus |
| `configuration` / `config_schema` | `JSONB` | config per plugin + schema de validare |
| `required_permissions` | `JSONB` | liste de permisiuni cerute |
| `is_latest`, `security_verified`, `download_count`, `rating` | — | coloane de marketplace, nefolosite azi |

Tabela `plugin_installations` (`models/plugin.py:72-88`) — **un rând per agent**:

| Coloană | Rol |
|---|---|
| `plugin_id`, `agent_id` | FK-uri (`agent_id` NULL = instalare globală) |
| `status` | `PENDING` / `INSTALLED` / `ENABLED` / `DISABLED` / `ERROR` |
| `error_message` | motivul eșecului, propagat din `JobResult` |
| `local_config` | config specifică agentului |
| `installed_version`, `installed_at`, `enabled_at` | tracking versiune |

## API-ul REST

Prefix `/api/v1/plugins` (`api/v1/routers/plugins.py`):

| Method | Path | Rol | RBAC |
|---|---|---|---|
| `GET` | `/plugins` | listă, cursor-paginat | orice user autentificat |
| `POST` | `/plugins/{id}/install` | pornește instalarea | **ADMIN** (`require_role("ADMIN")`) |
| `POST` | `/plugins/{id}/enable` | activează | ADMIN sau OPERATOR |
| `POST` | `/plugins/{id}/disable` | dezactivează | ADMIN sau OPERATOR |

> **Nu există endpoint de creare.** Un plugin nou se înregistrează printr-un rând în DB (migrare Alembic sau `INSERT` direct). `POST /plugins` nu există — marketplace-ul nu e implementat.

`POST /{id}/install` acceptă `agent_ids: list[UUID]` în query string. **Dacă lista e goală, se instalează pe toată flota activă** (`plugin_service.py:64-71`) — atenție: „instalează pe 3 agenți” și „instalează pe 4000 de agenți” arată identic în UI, pentru că UI-ul nu are agent-picker (`frontend/stores/plugins.ts:51`).

## Ciclul de viață al instalării

```
POST /plugins/{id}/install
  │
  ├─ 1. plugin_type != 'agent'?  → INSTALLED direct, fără job (control-plane/ui/notification)
  │
  ├─ 2. source_url gol?          → 400 "nothing for agents to download"
  ├─ 3. source_url în afara platform_url? → 400 "outside the platform origin — refused"
  │      (allowlist = origin-ul propriu al platformei; vezi plugin_service.py:77-83)
  │
  ├─ 4. șterge rândurile plugin_installations stale (retry path)
  ├─ 5. creează PluginInstallation per agent, status=PENDING_INSTALL
  ├─ 6. plugin.installation_status = INSTALLING
  │
  └─ 7. JobService.create_job(job_type="PLUGIN_INSTALL", parameters={
           plugin_id, plugin_name, plugin_version,
           download_url=source_url, checksum_sha256=plugin.checksum
       })
       → apoi publish NATS `lokilinux.plugin.install` (după commit!)
```

Puncte importante:

- **Publish după commit** (`plugin_service.py:128-137`) — un commit eșuat nu emite eveniment de instalare pentru o instalație rulată înapoi.
- **Jobul `PLUGIN_INSTALL` este un privileged job**: capability `PLUGIN_INSTALL`, risc `CRITICAL` (`services/job_envelope.py:53`, `agent/internal/security/capabilities.go:58`). Apare în registrul de capabilități, deci e eligible pentru envelope Ed25519 semnat.
- **Aprobare**: `PLUGIN_INSTALL` **nu** e în `_FORCE_APPROVAL_JOB_TYPES` (`services/job_service.py:30` — doar `CUSTOM_COMMAND` și `ANSIBLE_PLAYBOOK`). Deci instalarea unui plugin pe flotă **nu trece prin gate-ul de aprobare umană**; e protejată de RBAC (doar ADMIN) + signed envelope. Păstrează asta în minte când scrii un plugin care rulează pe root.
- **Fără `signature` în parametri.** `install_plugin` trimite `checksum_sha256`, dar **nu** trimite `signature`. Prin urmare, cu `enforce_signed_jobs=true` (agentul are `pluginVerifier() != nil`), instalarea eșuează cu „plugin signature missing — enforcement mode rejects unsigned plugins" (`agent/internal/modules/plugin_installer.go:107-116`). Cu `enforce_signed_jobs=false`, verificarea de semnătură e sărită (doar checksum).

## Ce face agentul la instalare

`agent/internal/modules/plugin_installer.go`:

1. Validă `plugin_name` / `plugin_version` — trebuie să fie `filepath.Base(name) == name`, altfel „invalid plugin_name" (blochează `../../etc/systemd/system`).
2. Descarcă `download_url` prin `http.Get` — **fără autentificare**. Deci URL-ul trebuie să fie accesibil public sau cu token în URL.
3. Scrie în `/opt/lokilinux/plugins/<name>/` — temp file + `os.Rename` (atomic, același filesystem).
4. Calculează SHA-256 în timpul descărcării (`io.MultiWriter` — artefactul nu e citit de două ori).
5. Compară cu `checksum_sha256`; **dacă parametrul lipsește → refuză** („refusing unsigned-by-hash install"). SHA-256 singur detectează corupția, nu un publisher malițios.
6. Dacă `verifier != nil` (mod enforcement): cere `signature` base64 peste exact `"sha256:" + digest`, verifică Ed25519. Fără semnătură → refuză.
7. Plasează la `/opt/lokilinux/plugins/<name>/<name>-<version>` și întoarce un `JobResult` de tip shell job (exit code, stdout, durată).

**Apoi se oprește.** Nu există cod care să încarce sau să execute artefactul. `grep -rn PluginDir agent/` dă doar installerul și testele lui.

## Cum se sincronizează rezultatele înapoi

`JobService._sync_plugin_installations` (`services/job_service.py:81-125`), apelată la fiecare `recompute_job_status`:

- citește `plugin_id` din `job.parameters`; dacă lipsește, iese;
- **sincronizează doar dacă `plugin.installation_status` e `INSTALLING` sau `INSTALLING_FAILED`** — un rezultat duplicat târziu nu poate clipească un plugin pe care utilizatorul l-a activat/dezactivat între timp;
- per agent: `COMPLETED` → `INSTALLED`; orice altă stare terminală → `ERROR` + `error_message` din `JobResult`;
- agregare: dacă toate instalările sunt `INSTALLED` → `plugin.installation_status = INSTALLED`; altfel `INSTALLING_FAILED`.

`PluginWorker` (`workers/plugin_worker.py`) abona la `lokilinux.plugin.install` și invalidează cache-ul (`plugin:list:*`, `plugin:{id}:*`) ca dashboard-ul să arate starea `INSTALLING` în timp real.

## Cum deblochezi un feature cu un plugin

Pattern-ul folosit de `ansible-automation`:

```python
# backend/lokilinux/api/v1/routers/playbooks.py:37-63
ANSIBLE_PLUGIN_NAME = "ansible-automation"

async def assert_plugin_enabled(db: AsyncSession, name: str) -> None:
    """403 dacă rândul Plugin lipsește sau nu are is_enabled."""
    plugin = (await db.execute(
        select(Plugin).where(Plugin.name == name)
    )).scalar_one_or_none()
    if plugin is None or not plugin.is_enabled:
        raise HTTPException(status_code=403, detail=f"Plugin '{name}' is not enabled")

def require_plugin_enabled(name: str):
    """Dependency factory — 403 dacă pluginul nu e enabled."""
    async def _check(db: AsyncSession = Depends(get_db)) -> None:
        await assert_plugin_enabled(db, name)
    return _check
```

Apoi, pe fiecare rută:

```python
@router.get("", response_model=list[PlaybookListItem],
            dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def list_playbooks(...): ...
```

`require_plugin_enabled` face **o interogare per request, fără cache** — deliberat (`playbooks.py:55-59`): rutele de playbook sunt trafic de admin, nu hot path. Cache-ul intră doar dacă devine bottleneck.

Gating pe alte tipuri de job (nu pe rute):

```python
# api/v1/routers/jobs.py:167-170
if job_type == "ANSIBLE_PLAYBOOK":
    await assert_plugin_enabled(db, ANSIBLE_PLUGIN_NAME)
```

## Scrierea unui plugin — pas cu pas

### Pas 1: decide tipul

| Vrei să… | `plugin_type` | Ce se întâmplă |
|---|---|---|
| Deblochezi un set de rute REST existente | `control-plane` | rând în DB + `is_enabled=true`; rutele se gatează cu `require_plugin_enabled` |
| Livrezi un artefact pe fiecare host | `agent` | `source_url` + `checksum` + job `PLUGIN_INSTALL` pe flotă |
| Adaugi UI | `ui` | tip declarat, fără runtime |
| Adaugi un canal de notificare | `notification` | tip declarat, fără runtime |

### Pas 2: scrie artefactul (doar pentru `plugin_type='agent'`)

Contractul de execuție **nu e implementat**. Cele două SDK-uri din `docs/arhitecture/plugin-sdk/` sunt design docs:

**Python** (`docs/arhitecture/plugin-sdk/python/base_plugin.py`):

```python
from base_plugin import BasePlugin, PluginContext

class MyPlugin(BasePlugin):
    def check(self) -> bool:
        """Gate: agentul sare collect() dacă False."""
        return bool(self.ctx.config.get("my_target_url"))

    def collect(self) -> dict:
        """Adună date; dict-ul se întoarce către control plane."""
        self.ctx.log(f"Collecting from {self.ctx.config['my_target_url']}")
        self.ctx.emit_metric("my.metric", 42.0)
        self.ctx.emit_alert("Title", "message", severity="WARNING")
        return {"source": "my-plugin", "items": []}

    def on_install(self) -> None:      # opțional
        self.ctx.log("installed")

    def on_uninstall(self) -> None:    # opțional
        self.ctx.log("uninstalling")

Plugin = MyPlugin   # loader entry point — trebuie asignat la numele modul "Plugin"
```

`PluginContext` oferă `plugin_id`, `agent_id`, `config: dict`, `data_dir`, plus `log()`, `emit_metric()`, `emit_alert()` — ultimele două scriu JSON pe **stdout**, iar agentul îl forwardează (protocolul e: `{"type": "metric"|"alert", ...}`).

**Go** (`docs/arhitecture/plugin-sdk/go/plugin.go`):

```go
package main

import "github.com/lokilinux/agent/pkg/plugin"

type MyPlugin struct{ ctx plugin.Context }

func (p *MyPlugin) Check() bool                      { return true }
func (p *MyPlugin) Collect() (map[string]any, error) { return map[string]any{"ok": true}, nil }
func (p *MyPlugin) OnInstall() error                 { return nil }
func (p *MyPlugin) OnUninstall() error               { return nil }

// Loader entry point — trebuie exportat ca "New".
func New(ctx plugin.Context) plugin.Plugin { return &MyPlugin{ctx: ctx} }
```

**Atenție la Go:** contractul cere un simbol exportat `New`, ceea ce implică `plugin.Open()` din stdlib — imposibil cu `CGO_ENABLED=0` (agentul e build static, CGO-free). Deci un plugin Go ar necesita un model subprocess/exec, nu `dlopen`. De aceea SDK-ul Python e varianta realistă, dar și ea nu are loader.

### Pas 3: împachetează și calculează checksum-ul

```bash
# artefactul e un singur fișier
tar czf my-plugin-1.0.0.tar.gz my_plugin/
sha256sum my-plugin-1.0.0.tar.gz
# → checksum-ul hex pe care îl pui în plugins.checksum
```

### Pas 4: publică artefactul la un URL

`source_url` trebuie să fie pe **același origin cu platforma** (`_same_origin` vs `PLATFORM_URL`) — altfel instalarea e refuzată. Practic:

- pune artefactul în object storage (RustFS/S3) și folosește URL-ul de download; sau
- pune-l într-un volum montat și servește-l printr-o rută a platformei.

**Atenție:** agentul descarcă cu `http.Get` **fără header de autentificare**. Un URL presigned S3 merge; o rută cu JWT nu.

### Pas 5: înregistrează pluginul în DB

Nu există `POST /plugins`. Fie migrare Alembic (ca `009_add_playbooks.py` pentru `ansible-automation`):

```python
op.execute("""
    INSERT INTO plugins (name, display_name, version, description, author,
                          plugin_type, manifest, is_enabled, is_installed,
                          installation_status, source_url, checksum)
    VALUES (
        'my-plugin', 'My Plugin', '1.0.0',
        'Ce face pluginul meu',
        'Numele meu',
        'agent',
        '{"name": "my-plugin", "version": "1.0.0", "entrypoint": "collect", "permissions": ["read:system"]}'::jsonb,
        false, false, 'PENDING_INSTALL',
        'https://storage.example.internal/my-plugin-1.0.0.tar.gz',
        '<sha256 hex din pasul 3>'
    )
""")
```

fie `INSERT` direct în DB (dev/test):

```sql
INSERT INTO plugins (name, display_name, version, plugin_type, manifest,
                      source_url, checksum, is_enabled, is_installed,
                      installation_status)
VALUES ('my-plugin', 'My Plugin', '1.0.0', 'agent',
        '{"entrypoint": "collect"}'::jsonb,
        'https://storage.example.internal/my-plugin-1.0.0.tar.gz',
        '<sha256 hex>', false, false, 'PENDING_INSTALL');
```

Pentru un plugin de tip `control-plane` (feature flag), `source_url` și `checksum` rămân NULL și `installation_status` = `INSTALLED` direct.

### Pas 6: instalează și activează

```bash
# instalare (doar ADMIN)
curl -X POST "$LOKI/api/v1/plugins/$PLUGIN_ID/install?agent_ids=<uuid1>,<uuid2>" \
     -H "Authorization: Bearer $ADMIN_JWT"

# sau pe toată flota activă (agent_ids gol → toți agenții ACTIVI)
curl -X POST "$LOKI/api/v1/plugins/$PLUGIN_ID/install" -H "Authorization: Bearer $ADMIN_JWT"

# activare (ADMIN sau OPERATOR) — doar după ce instalarea e INSTALLED
curl -X POST "$LOKI/api/v1/plugins/$PLUGIN_ID/enable" -H "Authorization: Bearer $ADMIN_JWT"
```

Verificare:

```bash
curl -s "$LOKI/api/v1/plugins" -H "Authorization: Bearer $JWT" | jq '.items[] | {name, installation_status, is_enabled}'
```

### Pas 7: gatează rutele tale

```python
from lokilinux.api.v1.routers.playbooks import require_plugin_enabled

MY_PLUGIN = "my-plugin"

@router.get("", dependencies=[Depends(require_plugin_enabled(MY_PLUGIN))])
async def my_feature(...): ...
```

Cât timp pluginul nu e enabled, rutile răspund **403 `Plugin 'my-plugin' is not enabled`**.

## Modelul de securitate

| Strat | Mecanism | Unde |
|---|---|---|
| **Cine poate instala** | `require_role("ADMIN")` pe `POST /{id}/install` | `routers/plugins.py:36-46` |
| **Cine poate activa** | `ADMIN` sau `OPERATOR` | `routers/plugins.py:52-60` |
| **Cine poate crea un job cu această capabilitate** | `CAPABILITY_MIN_ROLES["PLUGIN_INSTALL"] = {ADMIN}` | `utils/capability_rbac.py:29` |
| **Job type → capability** | `PLUGIN_INSTALL → PLUGIN_INSTALL` | `utils/capability_rbac.py:49` |
| **Risk tier (agent)** | `PLUGIN_INSTALL = CRITICAL` | `agent/internal/security/capabilities.go:58` |
| **Envelope semnat** | capability registry include `PLUGIN_INSTALL` → jobul primește `_envelope` Ed25519 când e eligibil | `services/job_envelope.py:53` |
| **Integritatea artefactului** | SHA-256 obligatoriu + Ed25519 peste `"sha256:<digest>"` în enforcement mode | `agent/internal/modules/plugin_installer.go:96-116` |
| **Path traversal** | `filepath.Base(name) == name` pentru name și version | `plugin_installer.go:47-56` |
| **Origin allowlist** | `source_url` trebuie pe origin-ul platformei | `services/plugin_service.py:77-83` |
| **Aprobare umană** | ❌ **nu e forțată** pentru `PLUGIN_INSTALL` | `services/job_service.py:30` |

Modelul de amenință al joburilor semnate e în [docs/security/EXECUTION_MODEL.md](../security/EXECUTION_MODEL.md); matricea capability↔rol în [docs/security/SECURITY_MATRIX.md](../security/SECURITY_MATRIX.md).

## Ce ar trebui construit ca runtime-ul să existe

Dacă vrei ca un plugin `agent` să ruleze efectiv, lipsesc (în ordine):

1. **Loader pe agent** — un runner de subprocess care pornește artefactul din `/opt/lokilinux/plugins/<name>/<name>-<version>` cu un timeout, și un parser al stream-ului stdout în formatul `{"type": "metric"|"alert", ...}` (protocolul e deja definit în SDK, dar nu are consumator).
2. **Discovery** — enumerarea `/opt/lokilinux/plugins/*/` și alegerea versiunii active; `installed_version` din DB există deja, dar agentul nu îl consultă.
3. **Trigger** — când rulează? La heartbeat? Pe interval? `check()`/`collect()` din SDK sugerează un model heartbeat, dar nu există wiring.
4. **Config per agent** — `PluginInstallation.local_config` există în DB; nu ajunge la agent.
5. **Execucție izolată** — `PLUGINS_SANDBOX_MODE`, `PLUGINS_MAX_MEMORY_MB`, `PLUGINS_MAX_CPU_CORES` sunt în `.env.example` și în `docs/arhitecture/LOKILINUX_DOCKER_DEPLOYMENT.md`, dar niciun cod nu le citește. `systemd-run` există deja în agent (`modules/systemd_run.go`) ca model de izolare — reutilizabil.
6. **Semnătură pe artefact în calea de instalare** — backendul nu trimite `signature` la agent, deci enforcement mode și plugin install se exclud mutual azi.

## Greșeli frecvite

| Greșeală | Simptom | Fix |
|---|---|---|
| `source_url` pe alt origin | 400 „outside the platform origin — refused" | pune artefactul pe origin-ul platformei |
| `checksum` gol sau lipsă | agentul refuză: „refusing unsigned-by-hash install" | calculează SHA-256 și pune-l în `plugins.checksum` |
| `enforce_signed_jobs=true` și fără `signature` | „plugin signature missing" | vezi §„Ce ar trebui construit" punctul 6 — momentan plugin install + enforcement sunt incompatibile |
| `install` cu `agent_ids` gol | se instalează pe **toată** flota activă | pasează explicit lista de UUID-uri |
| Enable înainte de instalare | 400 „Plugin must be INSTALLED or DISABLED to enable" | așteaptă `installation_status = INSTALLED` |
| Job `PLUGIN_INSTALL` duplicat | `ValueError` la `create_job` (dedup pe `dedup_key`) | verifică joburile active înainte să reinstalezi |
| Import de `require_plugin_enabled` din alt router | import circular | mută factory-ul într-un modul comun (ex. `utils/`) când ai >1 router care gatează |
| Scrierea unui „collector de compliance" ca plugin | nu apare niciodată în output | colectoarele de compliance sunt compilate în agent, nu plugin-uri |

## Referințe

| Document | Acoperă |
|---|---|
| `backend/lokilinux/models/plugin.py` | modelele ORM |
| `backend/lokilinux/services/plugin_service.py` | logica de instalare, origin allowlist, state machine |
| `backend/lokilinux/api/v1/routers/plugins.py` | API-ul REST + RBAC |
| `backend/lokilinux/api/v1/routers/playbooks.py:40-63` | `require_plugin_enabled` / `assert_plugin_enabled` |
| `backend/lokilinux/workers/plugin_worker.py` | consumator NATS, invalidare cache |
| `backend/lokilinux/services/job_service.py:81-125` | sincronizarea rezultatelor în `plugin_installations` |
| `backend/lokilinux/services/job_envelope.py:53` | `PLUGIN_INSTALL` → capability + risk |
| `backend/lokilinux/utils/capability_rbac.py:29,49` | capability ↔ roluri |
| `agent/internal/modules/plugin_installer.go` | download, checksum, semnătură, plasare |
| `agent/internal/security/capabilities.go:32,58` | registrul de capabilități al agentului |
| `docs/arhitecture/plugin-sdk/{go,python}/` | SDK-urile (design only) |
| `docs/compliance/03-AGENT-PLUGIN-SDK.md` | de ce colectoarele NU sunt plugin-uri |
| `docs/security/EXECUTION_MODEL.md` | modelul joburilor semnate |
| `docs/modules/07-ansible.md` | exemplu viu de plugin `control-plane` |
