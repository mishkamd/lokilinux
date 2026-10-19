"""Host header allowlist (ROADMAP P1r-1.2), driven with a bare ASGI app."""

import asyncio

import pytest

from lokilinux.middleware.trusted_hosts import TrustedHostsMiddleware, host_only


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def _status(host: str, *, enforce: bool) -> int:
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/x", "headers": [(b"host", host.encode())]}
    allowed = frozenset({"lokilinux-api", "example.com"})
    mw = TrustedHostsMiddleware(_app, allowed=allowed, enforce=enforce)
    asyncio.run(mw(scope, receive, send))
    return sent[0]["status"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.com:443", "example.com"),
        ("lokilinux-api:8000", "lokilinux-api"),
        ("[::1]:8000", "::1"),
        ("example.com", "example.com"),
    ],
)
def test_host_only_strips_port_and_case(raw, expected):
    assert host_only(raw) == expected


def test_enforce_rejects_unknown_host():
    assert _status("attacker.test", enforce=True) == 400


def test_enforce_allows_listed_host_with_port():
    assert _status("lokilinux-api:8000", enforce=True) == 200


def test_log_mode_lets_unknown_host_through():
    assert _status("attacker.test", enforce=False) == 200
