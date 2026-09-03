"""
LokiLinux — unit tests for lokilinux.object_storage's pure helpers.

No S3/network involved — sanitize_filename and validate_key are plain
string logic, tested in isolation (see conftest.FakeObjectStorage for the
integration-level fake used by router tests).
"""

from uuid import uuid4

import pytest

from lokilinux.object_storage import sanitize_filename, validate_key
from lokilinux.services.storage_service import CATEGORIES, _build_key


def test_sanitize_filename_strips_path_components() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("/etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\evil.exe") == "evil.exe"


def test_sanitize_filename_replaces_unsafe_characters() -> None:
    assert sanitize_filename("report (final)!.pdf") == "report__final__.pdf"


def test_sanitize_filename_null_byte() -> None:
    assert "\x00" not in sanitize_filename("evil\x00.txt")


def test_sanitize_filename_empty_falls_back() -> None:
    assert sanitize_filename("...") == "file"


def test_sanitize_filename_truncates() -> None:
    assert len(sanitize_filename("a" * 500)) == 200


@pytest.mark.parametrize(
    "key",
    ["../x", "a/../b", "/etc/passwd", "", "a\x00b", "x/../../y"],
)
def test_validate_key_rejects_traversal(key: str) -> None:
    with pytest.raises(ValueError):
        validate_key(key)


def test_validate_key_accepts_normal_key() -> None:
    validate_key("compliance/datastreams/abc-123/v1/ds.xml")


def test_build_key_uses_category_prefix() -> None:
    object_id = uuid4()
    key = _build_key("compliance.datastream", object_id, "ds.xml", version=1)
    assert key == f"compliance/datastreams/{object_id}/v1/ds.xml"


def test_build_key_unknown_category_raises() -> None:
    with pytest.raises(Exception):
        _build_key("not.a.category", uuid4(), "f.txt", version=1)


def test_categories_cover_expected_prefixes() -> None:
    assert CATEGORIES["compliance.report"] == "compliance/reports"
    assert CATEGORIES["automation.playbook"] == "automation/playbooks"
    assert CATEGORIES["upload"] == "uploads"
