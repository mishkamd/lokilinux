"""Unit tests for lokilinux/kms — lifecycle, rotation, fail-closed retirement."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lokilinux.kms import KeyManager, get_provider
from lokilinux.kms.errors import KeyRetired
from lokilinux.kms.provider import KeyRef


@pytest.fixture()
def keys_dir(tmp_path):
    return tmp_path / "keys"


def _seed_key(path):
    from pathlib import Path

    path = Path(path)
    key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))


def test_rotate_keeps_old_signatures_verifiable(keys_dir):
    km = KeyManager(str(keys_dir))
    v1 = km.ref(1) if False else None  # legacy layout handled by provider; versioned starts at create()
    ref1 = km.create(1, write_key_file=_seed_key)
    km.activate(ref1.version)
    assert km.active_version() == 1

    ref2 = km.rotate(write_key_file=_seed_key)
    assert km.active_version() == 2
    assert km.state_of(1) == "VERIFY_ONLY"   # old signatures stay verifiable
    assert km.verify_allowed(1)
    assert km.verify_allowed(2)


def test_retired_key_refused_for_verification(keys_dir):
    km = KeyManager(str(keys_dir))
    km.create(1, write_key_file=_seed_key)
    km.activate(1)
    km.retire(1)
    with pytest.raises(KeyRetired):
        km.enforce_verify_allowed(1)


def test_duplicate_version_rejected(keys_dir):
    km = KeyManager(str(keys_dir))
    km.create(1, write_key_file=_seed_key)
    from lokilinux.kms.keys import KMSError_Duplicate
    with pytest.raises(KMSError_Duplicate):
        km.create(1, write_key_file=_seed_key)


def test_factory_file_provider_from_env(monkeypatch, tmp_path):
    p = tmp_path / "k.key"
    _seed_key(p)
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(p))
    provider = get_provider({"provider": "file"})
    sig = provider.sign_message(KeyRef("job-signing", 1), b"msg")
    assert len(sig) == 64


def test_factory_rejects_unknown_provider():
    with pytest.raises(NotImplementedError):
        get_provider({"provider": "vault", "vault": {"address": "x"}})
