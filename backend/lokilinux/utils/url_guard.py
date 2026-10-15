"""
SSRF guard for server-side fetches of user-supplied URLs (ROADMAP P1r-2).

Checks the scheme, then the addresses the hostname resolves to. The hostname
string itself is never trusted, so a name pointing at 127.0.0.1 or the cloud
metadata endpoint is refused.

Blocking call (getaddrinfo): from async code, run it via asyncio.to_thread.

ponytail: check-then-fetch. The HTTP client resolves the name again, so a DNS
rebinding answer that flips between the two lookups can still get through.
Pinning the checked IP into the request is the upgrade path if that matters.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURLError(ValueError):
    """A URL was refused by the SSRF guard."""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)
    )


def assert_safe_url(url: str, allowed_hosts: frozenset[str] = frozenset()) -> None:
    """Raise UnsafeURLError unless `url` is http(s) and resolves only to public IPs.

    allowed_hosts: hostnames exempt from the address check (e.g. the platform's
    own origin). The scheme is still enforced for them.
    """
    try:
        parts = urlsplit(url)
        port = parts.port  # ValueError on bad port or unbalanced IPv6 brackets
    except ValueError as exc:
        raise UnsafeURLError("malformed URL") from exc
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {parts.scheme!r}")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError("missing host")
    if host in {h.lower() for h in allowed_hosts}:
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"host does not resolve: {host}") from exc
    except UnicodeError as exc:  # IDNA encoding fails, e.g. a DNS label over 63 chars
        raise UnsafeURLError(f"malformed host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # ponytail: no resolved IP in the message. It reaches API callers and is persisted.
        if _is_blocked(ip):
            raise UnsafeURLError(f"host resolves to a blocked address: {host}")
