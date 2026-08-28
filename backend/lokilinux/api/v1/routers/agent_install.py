"""
LokiLinux — Agent distribution & enrollment endpoints.

GET  /agent/packages           — URLs pachete + map `available` (locale) (JWT required)
POST /agent/enrollment-token   — generează token de enrollment 24h (ADMIN/OPERATOR)
GET  /agent/download           — servește binary local (enrollment token, fără JWT)
GET  /agent/download-latest    — servește binary versiunea curentă, public (folosit de `loki update`)
GET  /agent/download-direct    — servește binary local direct din dashboard (JWT ADMIN/OPERATOR)
GET  /agent/signing-key        — public key Ed25519 pt signed jobs, base64 raw (public by design — nu e secret)
GET  /agent/signing-keys       — hartă {"v":"b64"} ACTIVE+VERIFY_ONLY, pt installere/rotație
POST /agents/register          — înregistrare agent cu enrollment token + generare cert mTLS
"""

import datetime
import os
import uuid
from typing import Annotated

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.cache import RedisCache
from lokilinux.config import get_settings
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.agent_policy import EnrollmentToken
from lokilinux.models.audit import Setting
from lokilinux.services import ca_signer_client
from lokilinux.services.agent_policies import AgentPolicyService, EnrollmentTokenCreate

router = APIRouter()
register_router = APIRouter()

_ENROLLMENT_TTL = 86400  # 24h


# ── Enrollment token dependency (DB-backed — agent-policy-modernization P0) ──
#
# One store, one validator (AgentPolicyService.validate_enrollment_token) —
# no more parallel Redis TTL-only tokens. The offline installer spends the
# SAME token on two separate HTTP calls in sequence (download, then
# register — see install_agent.sh.tmpl), so this is a dependency FACTORY:
# /agent/download checks validity without spending a single-use token,
# only /agents/register actually consumes it.

def _verify_enrollment_token(*, consume: bool = False):
    async def _dep(
        authorization: Annotated[str | None, Header()] = None,
        db: AsyncSession = Depends(get_db),
    ) -> EnrollmentToken:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Enrollment token required")
        token = authorization.removeprefix("Bearer ").strip()
        return await AgentPolicyService(db).validate_enrollment_token(token, consume=consume)

    return _dep


# ── GET /agent/packages ───────────────────────────────────────────────────────

async def _get_agent_cfg(db: AsyncSession) -> tuple[str, str, str]:
    """Returnează (download_base, version, platform_url) din DB cu fallback la env."""
    s = get_settings()
    keys = ("agent.download_base", "agent.version", "agent.platform_url")
    rows = (await db.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    cfg = {r.key: r.value for r in rows}
    base = cfg.get("agent.download_base") or s.agent_download_base
    ver = cfg.get("agent.version") or s.agent_version
    plat = cfg.get("agent.platform_url") or s.platform_url
    return base, ver, plat


async def _platform_url(db: AsyncSession) -> tuple[str, str]:
    """(url, sursa) pentru install_command: DB override (UI "Configure URLs") > env."""
    row = (
        await db.execute(select(Setting).where(Setting.key == "agent.platform_url"))
    ).scalar_one_or_none()
    if row and row.value.strip():
        return row.value.rstrip("/"), "db"
    return get_settings().platform_url.rstrip("/"), "env"


@router.get("/packages")
async def get_packages(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict:
    base, v, plat = await _get_agent_cfg(db)
    base = base.rstrip("/")

    def pkg_url(filename: str) -> str:
        return f"{base}/{filename}" if base else ""

    def avail(pkg_os: str) -> dict:
        return {a: _package_available(pkg_os, a, v) for a in ("amd64", "arm64")}

    return {
        "version": v,
        "platform_url": plat,
        "rpm": {
            "amd64": pkg_url(f"lokilinux-agent-{v}-1.x86_64.rpm"),
            "arm64": pkg_url(f"lokilinux-agent-{v}-1.aarch64.rpm"),
        },
        "deb": {
            "amd64": pkg_url(f"lokilinux-agent_{v}_amd64.deb"),
            "arm64": pkg_url(f"lokilinux-agent_{v}_arm64.deb"),
        },
        "tar_gz": {
            "amd64": pkg_url(f"lokilinux-agent_{v}_linux_amd64.tar.gz"),
            "arm64": pkg_url(f"lokilinux-agent_{v}_linux_arm64.tar.gz"),
        },
        # Which packages the platform can serve directly (locally built), so the
        # dashboard can offer one-click download without an external download_base.
        "available": {
            "rpm": avail("rpm"),
            "deb": avail("deb"),
            "tar.gz": avail("tar.gz"),
        },
        "install_script": f"{plat}/api/v1/agent/install.sh",
    }


# ── GET /agent/install.sh ─────────────────────────────────────────────────────

_INSTALL_TMPL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "install_agent.sh.tmpl"
)


@router.get("/signing-key", response_class=PlainTextResponse)
async def get_signing_key() -> str:
    """Public Ed25519 job-signing key, base64(raw 32 bytes) — formatul pe care
    agent/internal/security.NewVerifier îl consumă direct. Public by design:
    cheia semnează joburile control-plane-ului; secretul rămâne în
    JOB_SIGNING_KEY_PATH (0600, niciodată pe agenți)."""
    key_path = os.environ.get("JOB_SIGNING_PUB_PATH", "/etc/lokilinux/certs/job_signing.pub")
    try:
        with open(key_path, "rb") as f:
            raw = f.read()
    except OSError:
        raise HTTPException(status_code=503, detail="job signing key not provisioned on this platform")
    if len(raw) != 32:
        # PKCS8/DER fallback: derive raw public bytes via cryptography
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            pub = serialization.load_pem_public_key(raw)
            if not isinstance(pub, Ed25519PublicKey):
                raise ValueError("not an Ed25519 key")
            raw = pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        except Exception as exc:  # noqa: BLE001 — orice format neașteptat = 503, nu crash
            raise HTTPException(status_code=503, detail=f"unusable signing key material: {exc}")
    import base64 as _b64

    return _b64.b64encode(raw).decode()


@router.get("/signing-keys")
async def get_signing_keys() -> dict:
    """Versioned job-signing public keys — {"1": "<b64>", "2": "<b64>", ...},
    ACTIVE+VERIFY_ONLY only (RETIRED never served). Installers write this
    into agent.yaml security.signing_pub_keys so a rotation via the admin
    KMS endpoints reaches agents enrolling AFTER it — /signing-key above
    only ever serves the single legacy key and is kept for old installers.
    Falls back to that same legacy key (as version "1") when no versioned
    signer is running on this platform."""
    from lokilinux.services.job_envelope import _get_signer

    signer = _get_signer()
    if signer is not None:
        keys = signer.public_keys()
        if keys:
            return keys
    return {"1": await get_signing_key()}


@router.get("/policy-signing-key")
async def get_policy_signing_key() -> str:
    """base64 raw ed25519 public key that signs desired-state AgentPolicy
    envelopes. Public by design (only the control plane holds the private
    half); installers pin it into agent.yaml policy.trusted_keys so the
    agent rejects any policy document not signed by this key."""
    from lokilinux.services.agent_policy_compiler import public_key_b64

    return public_key_b64()


@router.get("/signing-key.pem", response_class=PlainTextResponse)
async def get_signing_key_pem() -> str:
    """PEM form of the job-signing public key — consumed by installers that
    verify artifact signatures with `openssl pkeyutl -verify -pubin`."""
    pem_path = os.environ.get("JOB_SIGNING_PUB_PEM_PATH", "/etc/lokilinux/certs/job_signing.pub.pem")
    try:
        with open(pem_path) as f:
            return f.read()
    except OSError:
        raise HTTPException(status_code=503, detail="job signing key not provisioned on this platform")


@router.get("/install.sh", response_class=PlainTextResponse)
async def get_install_script(db: AsyncSession = Depends(get_db)) -> str:
    """Public bootstrap installer. The enrollment token is passed as a CLI arg
    (curl ... | bash -s -- --token=...), so no auth on the script itself."""
    _, _, plat = await _get_agent_cfg(db)
    with open(_INSTALL_TMPL_PATH) as f:
        script = f.read()
    return script.replace("__PLATFORM_URL__", plat)


# ── POST /agent/enrollment-token ──────────────────────────────────────────────

class EnrollmentTokenRequest(BaseModel):
    label: str = ""
    agent_group: str | None = None


@router.post("/enrollment-token")
async def create_enrollment_token(
    body: EnrollmentTokenRequest = EnrollmentTokenRequest(),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    """"Quick" convenience path over the exact same DB-backed store as
    POST /agent-policies/enrollment-tokens (plural) — kept as its own route
    for the existing "Add Agent" dialog (zero frontend break), single-use,
    24h TTL fixed."""
    plat, url_source = await _platform_url(db)
    result = await AgentPolicyService(db).issue_enrollment_token(
        EnrollmentTokenCreate(
            label=body.label, ttl_hours=24, single_use=True, agent_group=body.agent_group
        )
    )
    token = result["token"]
    return {
        "token": token,
        "expires_in": _ENROLLMENT_TTL,
        "install_command": (
            f"curl -fsSL {plat}/api/v1/agent/install.sh | "
            f"bash -s -- --token={token} --url={plat}"
        ),
        "url_source": url_source,
    }


# ── GET /agent/download ───────────────────────────────────────────────────────

_OS_ARCH_MAP: dict[str, dict[str, str]] = {
    "rpm": {
        # nfpm names rpm packages name-version-release.arch.rpm; release
        # defaults to "1" and isn't a value we control per-build.
        "amd64": "lokilinux-agent-{v}-1.x86_64.rpm",
        "arm64": "lokilinux-agent-{v}-1.aarch64.rpm",
    },
    "deb": {
        "amd64": "lokilinux-agent_{v}_amd64.deb",
        "arm64": "lokilinux-agent_{v}_arm64.deb",
    },
    "tar.gz": {
        "amd64": "lokilinux-agent_{v}_linux_amd64.tar.gz",
        "arm64": "lokilinux-agent_{v}_linux_arm64.tar.gz",
    },
}


def _resolve_package(pkg_os: str, arch: str, ver: str) -> tuple[str, str]:
    """Map (os, arch, version) to (filepath, filename) or raise. Shared by the
    enrollment-token and dashboard (JWT) download paths."""
    fmt = _OS_ARCH_MAP.get(pkg_os, {}).get(arch)
    if not fmt:
        raise HTTPException(status_code=400, detail=f"Unsupported os={pkg_os} arch={arch}")

    filename = fmt.format(v=ver)
    filepath = os.path.join(get_settings().agent_package_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=503,
            detail="Agent binary not yet built. Run `make agent-package` on the control plane.",
        )
    return filepath, filename


def _package_available(pkg_os: str, arch: str, ver: str) -> bool:
    fmt = _OS_ARCH_MAP.get(pkg_os, {}).get(arch)
    if not fmt:
        return False
    return os.path.exists(os.path.join(get_settings().agent_package_dir, fmt.format(v=ver)))


@router.get("/download-sig")
async def download_agent_sig(
    pkg_os: str = Query(...),
    arch: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> FileResponse:
    """Ed25519 signature over "sha256:<hex digest>" of the agent artifact —
    consumed by install.sh / loki update for supply-chain verification."""
    _, ver, _ = await _get_agent_cfg(db)
    filepath, filename = _sig_path(pkg_os, arch, ver)
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")


def _sig_path(pkg_os: str, arch: str, ver: str) -> tuple[str, str]:
    """Map (os, arch, version) to the sibling .sig of the tar.gz artifact.
    Mirrors _resolve_package's filename table for the tar.gz row."""
    fmt_map = {
        "tar.gz": "lokilinux-agent_{v}_linux_amd64.tar.gz",
    }
    if pkg_os != "tar.gz" or arch not in ("amd64", "arm64"):
        raise HTTPException(status_code=404, detail="signature not available for this format/arch")
    fname = fmt_map["tar.gz"].format(v=ver)
    if arch == "arm64":
        fname = fname.replace("_linux_amd64", "_linux_arm64")
    path = os.path.join(get_settings().agent_package_dir, fname)
    sig = path + ".sig"
    if not os.path.isfile(sig):
        raise HTTPException(status_code=404, detail="signature file not provisioned for this version")
    return sig, fname + ".sig"


@router.get("/download")
async def download_agent(
    pkg_os: str = Query(..., alias="os"),
    arch: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _token: EnrollmentToken = Depends(_verify_enrollment_token()),
) -> FileResponse:
    _, ver, _ = await _get_agent_cfg(db)
    filepath, filename = _resolve_package(pkg_os, arch, ver)
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")


@router.get("/download-latest")
async def download_agent_latest(
    pkg_os: str = Query(..., alias="os"),
    arch: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Public, unauthenticated — same exposure as /install.sh (also public).

    Used by `loki update` on already-enrolled hosts, which have no fresh
    enrollment token to spend. Always serves the currently configured
    agent.version — no arbitrary version in the query, so this can't be used
    to enumerate/pull historical builds.
    """
    _, ver, _ = await _get_agent_cfg(db)
    filepath, filename = _resolve_package(pkg_os, arch, ver)
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")


@router.get("/download-direct")
async def download_agent_direct(
    pkg_os: str = Query(..., alias="os"),
    arch: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> FileResponse:
    """Serve the locally-built agent package straight to an authenticated
    dashboard user — no enrollment token needed. Powers one-click generation
    from the /agents page."""
    _, ver, _ = await _get_agent_cfg(db)
    filepath, filename = _resolve_package(pkg_os, arch, ver)
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")


# ── POST /agents/register ─────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    hostname: str
    os_distro: str = ""
    os_version: str = ""
    arch: str = "amd64"
    kernel_version: str = ""
    # Re-enrollment proof-of-possession: required ONLY when `hostname` already
    # exists. Must be the current CA-signed client cert for that agent_id.
    existing_cert_pem: str | None = None


def _verify_reenrollment_proof(cert_pem: str | None, expected_agent_id: str) -> bool:
    """Gate for rotating credentials of an EXISTING agent identity.

    A stolen enrollment token alone must never mint certs for an identity an
    attacker merely knows the hostname of (docs/security/SECURITY_AUDIT.md
    HI-01). Possession of a currently-valid CA-issued cert for that exact
    agent_id is the only accepted proof.
    """
    if not cert_pem:
        return False
    s = get_settings()
    ca_path = os.path.join(s.agent_cert_dir, "ca.crt")
    if not os.path.exists(ca_path):
        return False
    try:
        with open(ca_path, "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        cert.verify_directly_issued_by(ca_cert)
    except Exception:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    if cert.not_valid_before_utc > now or cert.not_valid_after_utc < now:
        return False
    attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = attrs[0].value.strip() if attrs else ""
    if not (bool(cn) and cn.lower() == expected_agent_id.strip().lower()):
        return False

    return bool(cn) and cn.lower() == expected_agent_id.strip().lower()


def _cert_serial_hex(cert_pem: str) -> str | None:
    """P11 helper: hex serial of a PEM cert, None when unparseable."""
    try:
        return format(x509.load_pem_x509_certificate(cert_pem.encode()).serial_number, "x")
    except Exception:
        return None


async def _generate_agent_cert(agent_id: str) -> tuple[str, str, str]:
    """Generate mTLS cert for agent, signed by the isolated ca-signer service
    (this process never touches ca.key — see services/ca_signer_service.py).
    Returns (cert_pem, key_pem, ca_pem)."""
    s = get_settings()
    ca_cert_path = os.path.join(s.agent_cert_dir, "ca.crt")

    if not os.path.exists(ca_cert_path):
        return "", "", ""

    agent_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = agent_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    try:
        cert_pem = await ca_signer_client.sign_agent_cert(
            agent_id=agent_id,
            public_key_pem=public_key_pem,
            validity_days=s.agent_cert_ttl_days,
        )
    except ca_signer_client.CASignerError:
        return "", "", ""

    key_pem = agent_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    with open(ca_cert_path) as f:
        ca_pem = f.read()

    return cert_pem, key_pem, ca_pem


@register_router.post("/register")
async def register_agent(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    token: EnrollmentToken = Depends(_verify_enrollment_token(consume=True)),
) -> dict:
    existing = (
        await db.execute(select(Agent).where(Agent.hostname == body.hostname))
    ).scalars().first()

    if existing is not None:
        # HI-01: hostname alone no longer grants identity takeover — the
        # caller must prove possession of the current agent certificate.
        if not _verify_reenrollment_proof(body.existing_cert_pem, existing.agent_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Hostname already registered. Re-enrollment requires the current "
                    "agent certificate in `existing_cert_pem`; use a new hostname or "
                    "contact an administrator to decommission the old agent."
                ),
            )

        # P11: a revoked certificate must not resurrect its identity through
        # re-enrollment — same fail-closed policy as the heartbeat gate.
        s = get_settings()
        serial_hex = _cert_serial_hex(body.existing_cert_pem)
        try:
            from lokilinux.services import cert_revocation

            await cert_revocation.assert_not_revoked(
                cache, serial_hex,
                enabled=s.certificate_revocation_enabled,
                fail_closed=s.certificate_revocation_fail_closed,
            )
        except cert_revocation.CertificateRevoked:
            raise HTTPException(status_code=403, detail="certificate revoked")
        except cert_revocation.RevocationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        agent_id = existing.agent_id
        existing.status = AgentStatus.PENDING
        existing.os_distro = body.os_distro
        existing.os_version = body.os_version
        existing.arch = body.arch
        existing.kernel_version = body.kernel_version
        if token.agent_group is not None:
            existing.agent_group_id = token.agent_group
    else:
        agent_id = str(uuid.uuid4())
        db.add(Agent(
            agent_id=agent_id,
            status=AgentStatus.PENDING,
            hostname=body.hostname,
            os_distro=body.os_distro,
            os_version=body.os_version,
            arch=body.arch,
            kernel_version=body.kernel_version,
            agent_group_id=token.agent_group,
        ))
    await db.flush()
    await db.commit()

    agent_cert, agent_key, ca_cert = await _generate_agent_cert(agent_id)

    return {
        "agent_id": agent_id,
        "agent_cert": agent_cert,
        "agent_key": agent_key,
        "ca_cert": ca_cert,
    }
