"""SSRF guard (ROADMAP P1r-2). Literal IPs need no DNS; the hostname cases mock getaddrinfo."""

import socket

import pytest

from lokilinux.utils import url_guard
from lokilinux.utils.url_guard import UnsafeURLError, assert_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5:8080/",
        "http://192.168.1.1/",
        "http://100.64.1.1/",  # CGNAT, not flagged by is_private
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
    ],
)
def test_internal_addresses_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://8.8.8.8/", "ftp://8.8.8.8/x"])
def test_scheme_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_public_address_allowed():
    assert_safe_url("https://8.8.8.8/x")


def test_allowed_host_skips_address_check(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("allowed host must not be resolved")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    assert_safe_url(
        "http://Platform.Internal:8000/x", allowed_hosts=frozenset({"platform.internal"})
    )


def test_hostname_resolving_to_loopback_refused(monkeypatch):
    def fake(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeURLError, match="blocked address"):
        assert_safe_url("https://metadata.example.test/")


def test_unresolvable_host_refused(monkeypatch):
    # Mocked: some resolvers answer every name (wildcard DNS), so real lookups aren't reliable.
    def nxdomain(*_a, **_k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", nxdomain)
    with pytest.raises(UnsafeURLError, match="does not resolve"):
        assert_safe_url("https://nonexistent.invalid/")


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1/x",  # unbalanced IPv6 bracket
        "http://127.0.0.1:99999/",  # port out of range
        "http://127.0.0.1:abc/",  # non-numeric port
        "http://[::1]:99999/",
        "http://" + "a" * 70 + ".example/",  # DNS label over 63 chars, fails IDNA encoding
    ],
)
def test_malformed_url_refused_as_unsafe(url):
    with pytest.raises(UnsafeURLError) as info:
        assert_safe_url(url)
    assert type(info.value) is UnsafeURLError


def test_blocked_message_omits_resolved_ip(monkeypatch):
    def fake(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeURLError) as info:
        assert_safe_url("https://metadata.example.test/")
    message = str(info.value)
    assert "resolves to a blocked address" in message
    assert "metadata.example.test" in message
    assert "127.0.0.1" not in message
