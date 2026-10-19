"""
LokiLinux — Debian/Ubuntu CVE matching through OSV (ROADMAP R4).

dnf/yum hosts get their CVEs from the agent (`dnf updateinfo`). Debian and
Ubuntu had no CVE source at all. This matches their installed packages
against OSV (https://osv.dev), centrally, so the agent never carries feed data.

OSV indexes Debian and Ubuntu records by SOURCE package name, so lookups use
the agent-reported source (libssl3 -> openssl) and fall back to the binary
name when the agent didn't send one. Results come back as DEBIAN-CVE-* or
UBUNTU-CVE-* ids, which map to CVE-* ids. Other OSV ids (DSA, USN) are skipped.

Each run recomputes from the packages table. Rows for package versions that
are no longer installed are removed. A CVE that OSV later withdraws is not
removed yet.

ponytail: one querybatch per 500 distinct (ecosystem, package, version)
triples, every run. Fine for a fleet of thousands; past that, cache results
per triple and only query new ones.
"""

import uuid
from collections import defaultdict

import httpx
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent
from lokilinux.models.cve import CVE, AgentVulnerability, Package

OSV_BATCH_SIZE = 500
_MAX_PAGES = 10
_INSERT_CHUNK = 5000
_DISTROS = ["debian", "ubuntu"]


def ecosystem_for(os_distro: str | None, os_version: str | None) -> str | None:
    distro = (os_distro or "").strip().lower()
    parts = (os_version or "").strip().split(".")
    if distro == "debian" and parts[0].isdigit():
        return f"Debian:{parts[0]}"
    if distro == "ubuntu" and len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        release = f"{parts[0]}.{parts[1]}"
        is_lts = parts[1] == "04" and int(parts[0]) % 2 == 0
        return f"Ubuntu:{release}:LTS" if is_lts else f"Ubuntu:{release}"
    return None


def cve_ids_from_osv(vuln_ids) -> set[str]:  # type: ignore[no-untyped-def]
    cves: set[str] = set()
    for vid in vuln_ids:
        for prefix in ("DEBIAN-", "UBUNTU-"):
            if vid.startswith(prefix + "CVE-"):
                cves.add(vid[len(prefix):])
        if vid.startswith("CVE-"):
            cves.add(vid)
    return cves


async def match_packages(db: AsyncSession, client: httpx.AsyncClient, *, base_url: str) -> int:
    """Refresh Debian/Ubuntu agent vulnerabilities. Returns rows written."""
    rows = (await db.execute(
        select(
            Agent.id, Agent.os_distro, Agent.os_version,
            Package.name, Package.version, Package.source_package,
        )
        .join(Package, Package.agent_id == Agent.id)
        .where(Agent.os_distro.in_(_DISTROS))
    )).all()

    # (ecosystem, lookup name, version) -> [(agent_id, binary name)]
    groups: dict[tuple[str, str, str], list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for agent_id, distro, os_version, name, version, source in rows:
        ecosystem = ecosystem_for(distro, os_version)
        if ecosystem is None:
            continue
        groups[(ecosystem, source or name, version)].append((agent_id, name))
    if not groups:
        return 0

    keys = list(groups)
    found: dict[tuple[str, str, str], set[str]] = {}
    for start in range(0, len(keys), OSV_BATCH_SIZE):
        chunk = keys[start:start + OSV_BATCH_SIZE]
        resp = await client.post(f"{base_url}/v1/querybatch", json={"queries": [
            {"package": {"name": name, "ecosystem": eco}, "version": version}
            for eco, name, version in chunk
        ]})
        resp.raise_for_status()
        for key, result in zip(chunk, resp.json().get("results", [])):
            vulns = list(result.get("vulns") or [])
            token = result.get("next_page_token")
            pages = 0
            while token and pages < _MAX_PAGES:
                pages += 1
                eco, name, version = key
                page = await client.post(f"{base_url}/v1/query", json={
                    "package": {"name": name, "ecosystem": eco},
                    "version": version,
                    "page_token": token,
                })
                page.raise_for_status()
                data = page.json()
                vulns.extend(data.get("vulns") or [])
                token = data.get("next_page_token")
            found[key] = cve_ids_from_osv(v.get("id", "") for v in vulns)

    all_cves = set().union(*found.values()) if found else set()
    if all_cves:
        await db.execute(
            pg_insert(CVE).values([{"cve_id": c} for c in sorted(all_cves)])
            .on_conflict_do_nothing(index_elements=["cve_id"])
        )

    out = []
    for key, cves in found.items():
        for agent_id, binary in groups[key]:
            for cve in cves:
                out.append({
                    "agent_id": agent_id, "cve_id": cve,
                    "package_name": binary, "package_version": key[2],
                })
    for start in range(0, len(out), _INSERT_CHUNK):
        await db.execute(
            pg_insert(AgentVulnerability).values(out[start:start + _INSERT_CHUNK])
            .on_conflict_do_nothing(constraint="uq_agent_vuln_agent_cve_package")
        )

    # Drop rows for package versions the agent no longer has installed.
    await db.execute(delete(AgentVulnerability).where(
        AgentVulnerability.agent_id.in_(select(Agent.id).where(Agent.os_distro.in_(_DISTROS))),
        ~exists().where(
            Package.agent_id == AgentVulnerability.agent_id,
            Package.name == AgentVulnerability.package_name,
            Package.version == AgentVulnerability.package_version,
        ),
    ))
    await db.commit()
    return len(out)
