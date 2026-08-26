"""CRL-lite certificate revocation (plan P11).

A single Redis SET holds revoked certificate serials (hex, lowercase).
Lookups happen ONLY at mTLS authentication points (heartbeat stream open,
agent register) — never per job/event, so Redis stays out of the hot path.

Semantics:
  - disabled            -> no-op (compatibility mode)
  - member              -> CertificateRevoked
  - redis unreachable   -> RevocationUnavailable if fail_closed else log+pass
"""

import re
from typing import Union

import structlog

from lokilinux.cache import RedisCache

logger = structlog.get_logger()

REVOKED_KEY = "lokilinux:certs:revoked"

# X.509 serial numbers are positive integers up to 20 octets; store hex.
_SERIAL_RE = re.compile(r"^[0-9a-f]{1,40}$")


class CertificateRevoked(Exception):
    def __init__(self, serial: str):
        self.serial = serial
        super().__init__(f"certificate {serial} is revoked")


class RevocationUnavailable(Exception):
    """Revocation check could not be answered (Redis unreachable)."""


def normalize_serial(serial: Union[int, str]) -> str:
    """Accepts int or hex string; returns canonical lowercase-hex form."""
    if isinstance(serial, int):
        if serial < 0:
            raise ValueError("serial must be non-negative")
        return format(serial, "x")
    s = serial.strip().lower().removeprefix("0x")
    if not _SERIAL_RE.match(s):
        raise ValueError("invalid certificate serial format")
    return s


async def revoke(cache: RedisCache, serial: Union[int, str]) -> str:
    norm = normalize_serial(serial)
    await cache.sadd(REVOKED_KEY, norm)
    logger.info("certificate.revoked", serial=norm)
    return norm


async def unrevoke(cache: RedisCache, serial: Union[int, str]) -> bool:
    """Returns True when the serial was present and is now removed."""
    norm = normalize_serial(serial)
    removed = await cache.srem(REVOKED_KEY, norm)
    logger.info("certificate.unrevoked", serial=norm, was_present=bool(removed))
    return bool(removed)


async def list_revoked(cache: RedisCache) -> list[str]:
    return sorted(await cache.smembers(REVOKED_KEY))


async def assert_not_revoked(
    cache: RedisCache,
    serial: Union[int, str],
    *,
    enabled: bool = True,
    fail_closed: bool = True,
) -> None:
    """Raises CertificateRevoked for a revoked cert. With fail_closed=True a
    Redis outage raises RevocationUnavailable (caller rejects the connection);
    with False it degrades to allow-with-WARN (compat deployments)."""
    if not enabled:
        return
    try:
        norm = normalize_serial(serial)
    except ValueError:
        # A certificate we cannot even parse a serial from is not checkable —
        # same policy branch as an outage.
        if fail_closed:
            raise RevocationUnavailable("unparseable certificate serial")
        logger.warning("revocation.skip_unparseable_serial")
        return
    try:
        if await cache.sismember(REVOKED_KEY, norm):
            raise CertificateRevoked(norm)
    except CertificateRevoked:
        raise
    except Exception as exc:  # redis errors bubble as domain error
        logger.error("revocation.lookup_failed", error=str(exc))
        if fail_closed:
            raise RevocationUnavailable("revocation store unreachable") from exc
