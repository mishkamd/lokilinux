"""
LokiLinux — Agent distribution & enrollment endpoints.

GET  /agent/packages           — URLs pachete + map `available` (locale) (JWT required)
POST /agent/enrollment-token   — generează token de enrollment 24h (ADMIN/OPERATOR)
GET  /agent/download           — servește binary local (enrollment token, fără JWT)
GET  /agent/download-latest    — servește binary versiunea curentă, public (folosit de `loki update`)
GET  /agent/download-direct    — servește binary local direct din dashboard (JWT ADMIN/OPERATOR)
GET  /agent/signing-key        — public key Ed25519 pt signed jobs, base64 raw (public by design — nu e secret)
POST /agents/register          — înregistrare agent cu enrollment token + generare cert mTLS
"""

import datetime
import os
import secrets
import uuid
from typing import Annotated

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
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
from lokilinux.models.audit import Setting

router = APIRouter()
register_router = APIRouter()

_ENROLLMENT_TTL = 86400  # 24h


# ── Enrollment token dependency (Redis, nu JWKS) ──────────────────────────────

async def _verify_enrollment_token(
    authorization: Annotated[str | None, Header()] = None,
    cache: RedisCache = Depends(get_cache),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Enrollment token required")
    token = authorization.removeprefix("Bearer ").strip()
    exists = await cache.exists(f"enrollment:{token}")
    if not exists:
        raise HTTPException(status_code=403, detail="Invalid or expired enrollment token")
    return token


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


@router.post("/enrollment-token")
async def create_enrollment_token(
    body: EnrollmentTokenRequest = EnrollmentTokenRequest(),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    await cache.set_cached(f"enrollment:{token}", body.label or "active", ttl=_ENROLLMENT_TTL)
    return {
        "token": token,
        "expires_in": _ENROLLMENT_TTL,
        "install_command": (
            f"curl -fsSL {s.platform_url}/api/v1/agent/install.sh | "
            f"bash -s -- --token={token} --url={s.platform_url}"
        ),
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
    token: str = Depends(_verify_enrollment_token),
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
    return bool(cn) and cn.lower() == expected_agent_id.strip().lower()


def _generate_agent_cert(agent_id: str) -> tuple[str, str, str]:
    """Generate mTLS cert for agent signed by local CA. Returns (cert_pem, key_pem, ca_pem)."""
    s = get_settings()
    ca_cert_path = os.path.join(s.agent_cert_dir, "ca.crt")
    ca_key_path = os.path.join(s.agent_cert_dir, "ca.key")

    if not (os.path.exists(ca_cert_path) and os.path.exists(ca_key_path)):
        return "", "", ""

    with open(ca_cert_path, "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())
    with open(ca_key_path, "rb") as f:
        ca_key = serialization.load_pem_private_key(f.read(), password=None)

    agent_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, agent_id),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LokiLinux"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(agent_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key_pem = agent_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

    with open(ca_cert_path) as f:
        ca_pem = f.read()

    return cert_pem, key_pem, ca_pem


@register_router.post("/register")
async def register_agent(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    token: str = Depends(_verify_enrollment_token),
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
        agent_id = existing.agent_id
        existing.status = AgentStatus.PENDING
        existing.os_distro = body.os_distro
        existing.os_version = body.os_version
        existing.arch = body.arch
        existing.kernel_version = body.kernel_version
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
        ))
    await db.flush()
    await db.commit()

    # token single-use
    await cache.invalidate(f"enrollment:{token}")

    agent_cert, agent_key, ca_cert = _generate_agent_cert(agent_id)

    return {
        "agent_id": agent_id,
        "agent_cert": agent_cert,
        "agent_key": agent_key,
        "ca_cert": ca_cert,
    }
