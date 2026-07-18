"""Unit tests for agent package resolution/availability.

Regression guard for the rpm filename mismatch: nfpm names rpm packages
name-version-release.arch.rpm (release defaults to "1"), so the map here
must include the "-1" segment or every rpm build looks "unavailable" to
the dashboard even though the file exists on disk.
"""

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from lokilinux.api.v1.routers.agent_install import _package_available, _resolve_package

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
