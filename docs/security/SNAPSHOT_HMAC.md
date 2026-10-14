# HMAC pe snapshot-uri de compliance (ROADMAP P1r-3.1, 3.3)

> Status: DESIGN, neimplementat. Cere aprobare înainte de cod: schimbă protocolul agent ↔ server ↔ serviciu compliance, pe o flotă live.
> Decizie deja luată: cheia per agent se stochează în DB, cu rotație.

## Problema

Un snapshot de compliance ajunge la serviciul Go ca `{agent_id, domain, content_hash, facts}`. Consumerul recalculează BLAKE3 pe `facts` și compară cu `content_hash` (`ingest.go:110-114`). Asta prinde corupția, dar nu falsificarea: cine poate publica pe NATS poate calcula el însuși hash-ul pentru facts false. Din acest motiv publicarea externă a fost închisă prin autentificare NATS (P0). Un agent compromis, care are propriul certificat, poate însă trimite facts false pentru alt agent sau alt domeniu.

## Decizia de design: HMAC pe hash, nu pe JSON

Encoding-ul canonic e JSON Go cu chei sortate (`agent/internal/compliance/canonical.go`). Reproducerea lui exactă în Python (escaping, formatul numerelor) e fragilă, iar o nepotrivire ar respinge snapshot-uri valide.

Semnăm în schimb un string care e deja canonic:

```
mac = HMAC-SHA256(key[key_id], "v1|" + agent_id + "|" + domain + "|" + content_hash)
```

`content_hash` e recalculat de consumer pe facts, deci legătura facts ↔ hash rămâne verificată. HMAC-ul leagă hash-ul de cheia agentului. Un atacator fără cheie nu poate produce un `mac` valid pentru un hash nou.

## Componente

| Strat | Ce se schimbă |
|---|---|
| Agent (Go) | Generează `mac` pentru fiecare domeniu din `domain_full`. Ține ultimele 2 chei (`key_id` curent și precedent) în SQLite, ca rotația să nu rupă snapshot-urile în zbor. |
| Heartbeat (proto) | Câmp nou `domain_macs` (map domeniu → `{key_id, mac}`), numere de câmp 13–19 libere. Wire JSON, deci ambele părți se actualizează. |
| Cheia (server) | Coloane noi pe `agents`: `snapshot_hmac_key` (bytea, criptată la rest cu KMS-ul existent, sau în clar cu acces restricționat, de decis) și `snapshot_hmac_key_id`. Migrația 053. |
| Livrare cheie | Serverul include cheia în răspunsul de heartbeat doar când agentul raportează un `key_id` diferit de al lui. Agentul o salvează și confirmă `key_id` în heartbeat-ul următor. |
| Backend (Python) | Transmite `domain_macs` în mesajul NATS `lokilinux.compliance.snapshot.{domain}`. |
| Consumer (Go) | Dacă mesajul are `mac`, îl verifică cu cheia `key_id` a agentului. Dacă nu are, acceptă (fail-open pentru agenții vechi). Flag `ENFORCE_SNAPSHOT_HMAC` respinge mesajele fără `mac`. |

## Rotație

- Rotația e declanșată manual, din UI sau API, nu periodic. Rotația automată e o decizie separată.
- La rotație serverul generează cheie nouă cu `key_id` incrementat. Agentul primește cheia în heartbeat și continuă să semneze cu cea nouă. Consumerul acceptă ambele chei pentru o fereastră de 1 oră.

## Ce nu rezolvă

- Un agent compromis, cu cheia lui încă validă, poate semna facts false pentru el însuși. Asta e limita inerentă, comună cu certificatul de agent.
- Cheia din DB e la fel de sensibilă ca CA-ul: cine citește DB-ul poate semna snapshot-uri. De aceea varianta KMS e de luat în calcul.

## Întrebări deschise (de aprobat înainte de cod)

1. Cheia se livrează în răspunsul de heartbeat (propus) sau la enrollment? Enrollment-ul e mai curat, dar agenții existenți ar rămâne fără cheie până la re-enrollment.
2. Cheia se criptează în DB cu KMS (recomandat) sau rămâne în clar sub restricție de acces?
3. Când trecem `ENFORCE_SNAPSHOT_HMAC` pe `true`? Propunere: după ce toată flota raportează `mac` pentru 7 zile consecutive, verificat din metrici.

## Verificare

- Unit test Go: `mac` calculat de agent se verifică în consumer pentru același `(agent_id, domain, content_hash, key_id)`.
- Unit test Go: mesaj cu `mac` alterat, sau `key_id` necunoscut → respins.
- Unit test Go: mesaj fără `mac` → acceptat cât timp `ENFORCE_SNAPSHOT_HMAC=false`.
- Test de integrare pe stack: heartbeat cu snapshot, rotație, snapshot după rotație, rezultat verificat în `inventory_snapshots`.
