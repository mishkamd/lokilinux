"""Unit tests for agent package resolution/availability.

Regression guard for the rpm filename mismatch: nfpm names rpm packages
name-version-release.arch.rpm (release defaults to "1"), so the map here
must include the "-1" segment or every rpm build looks "unavailable" to
the dashboard even though the file exists on disk.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException

from lokilinux.api.v1.routers.agent_install import _generate_agent_cert, _package_available, _resolve_package
from lokilinux.services import ca_signer_client

_SETTINGS_PATH = "lokilinux.api.v1.routers.agent_install.get_settings"


def _patch_settings(monkeypatch, pkg_dir):
    monkeypatch.setattr(_SETTINGS_PATH, lambda: SimpleNamespace(agent_package_dir=str(pkg_dir)))


def test_package_available_true_when_file_exists(tmp_path, monkeypatch):
    (tmp_path / "lokilinux-agent_1.2.3_linux_amd64.tar.gz").write_bytes(b"x")
    _patch_settings(monkeypatch, tmp_path)
    assert _package_available("tar.gz", "amd64", "1.2.3") is True


def test_package_available_false_when_file_missing(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    assert _package_available("rpm", "amd64", "1.2.3") is False


def test_package_available_false_for_unknown_os(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    assert _package_available("msi", "amd64", "1.2.3") is False


def test_rpm_filename_includes_nfpm_release_suffix(tmp_path, monkeypatch):
    (tmp_path / "lokilinux-agent-1.2.3-1.x86_64.rpm").write_bytes(b"x")
    _patch_settings(monkeypatch, tmp_path)
    assert _package_available("rpm", "amd64", "1.2.3") is True


def test_resolve_package_returns_path_when_exists(tmp_path, monkeypatch):
    filename = "lokilinux-agent-1.2.3-1.x86_64.rpm"
    (tmp_path / filename).write_bytes(b"x")
    _patch_settings(monkeypatch, tmp_path)
    filepath, resolved_name = _resolve_package("rpm", "amd64", "1.2.3")
    assert resolved_name == filename
    assert os.path.exists(filepath)


def test_resolve_package_raises_503_when_missing(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        _resolve_package("deb", "amd64", "1.2.3")
    assert exc_info.value.status_code == 503


def test_resolve_package_raises_400_for_unsupported_combo(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        _resolve_package("msi", "amd64", "1.2.3")
    assert exc_info.value.status_code == 400


# ── _generate_agent_cert — PKI Faza 4: signs through the isolated ─────────────
# ca-signer service instead of opening ca.key directly (see ca_signer_client.py).

def _patch_cert_settings(monkeypatch, certs_dir, ttl_days=30):
    monkeypatch.setattr(
        _SETTINGS_PATH,
        lambda: SimpleNamespace(agent_cert_dir=str(certs_dir), agent_cert_ttl_days=ttl_days),
    )


def test_generate_agent_cert_never_opens_ca_key(tmp_path, monkeypatch):
    """No ca.key file exists anywhere in tmp_path — if this function fell
    back to reading one directly, it would fail. Proves the isolation."""
    (tmp_path / "ca.crt").write_text("placeholder — only echoed back verbatim, never parsed")
    _patch_cert_settings(monkeypatch, tmp_path)

    calls = []

    async def fake_sign(agent_id, public_key_pem, validity_days):
        calls.append((agent_id, validity_days))
        assert "PUBLIC KEY" in public_key_pem
        return "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"

    monkeypatch.setattr(ca_signer_client, "sign_agent_cert", fake_sign)

    cert_pem, key_pem, ca_pem = asyncio.run(_generate_agent_cert("agent-xyz"))

    assert calls == [("agent-xyz", 30)]
    assert cert_pem == "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
    assert ca_pem == "placeholder — only echoed back verbatim, never parsed"
    # key_pem is a real, freshly-generated private key — round-trips through
    # the standard PEM loader.
    serialization.load_pem_private_key(key_pem.encode(), password=None)


def test_generate_agent_cert_respects_ttl_from_settings(tmp_path, monkeypatch):
    (tmp_path / "ca.crt").write_text("x")
    _patch_cert_settings(monkeypatch, tmp_path, ttl_days=7)

    captured = {}

    async def fake_sign(agent_id, public_key_pem, validity_days):
        captured["validity_days"] = validity_days
        return "cert"

    monkeypatch.setattr(ca_signer_client, "sign_agent_cert", fake_sign)
    asyncio.run(_generate_agent_cert("agent-1"))
    assert captured["validity_days"] == 7


def test_generate_agent_cert_returns_empty_when_ca_cert_missing(tmp_path, monkeypatch):
    _patch_cert_settings(monkeypatch, tmp_path)
    cert_pem, key_pem, ca_pem = asyncio.run(_generate_agent_cert("agent-1"))
    assert (cert_pem, key_pem, ca_pem) == ("", "", "")


def test_generate_agent_cert_returns_empty_on_signer_failure(tmp_path, monkeypatch):
    (tmp_path / "ca.crt").write_text("x")
    _patch_cert_settings(monkeypatch, tmp_path)

    async def failing_sign(agent_id, public_key_pem, validity_days):
        raise ca_signer_client.CASignerError("ca-signer unreachable: test")

    monkeypatch.setattr(ca_signer_client, "sign_agent_cert", failing_sign)
    cert_pem, key_pem, ca_pem = asyncio.run(_generate_agent_cert("agent-1"))
    assert (cert_pem, key_pem, ca_pem) == ("", "", "")
