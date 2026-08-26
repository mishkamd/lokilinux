"""FileSigningProvider — file-based keys behind the SigningProvider protocol.

Two layouts supported:
  1. LEGACY (compat): a single key file (JOB_SIGNING_KEY_PATH, raw-32 seed or
     PKCS8 PEM) — treated as key_id="job-signing", version=1.
  2. VERSIONED: {keys_dir}/{key_id}/v{n}.key files + metadata.json maintained
     by KeyManager.

Private material is loaded lazily and cached in-process only. Error messages
carry key_id/version/reason exclusively (plan §15).
"""

import os
from functools import lru_cache
from typing import Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from lokilinux.kms.errors import KeyNotFound, ProviderUnavailable
from lokilinux.kms.provider import KeyRef

LEGACY_KEY_ID = "job-signing"
LEGACY_VERSION = 1


def _load_private(path: str) -> Ed25519PrivateKey:
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key


class FileSigningProvider:
    def __init__(self, legacy_key_path: str):
        self._legacy_path = legacy_key_path
        self._versioned_dir: Optional[str] = None
        self._priv_cache: Dict[KeyRef, Ed25519PrivateKey] = {}
        self._pub_cache: Dict[KeyRef, Ed25519PublicKey] = {}
        # Fail-fast on unusable material: construction validates the legacy
        # key exists and parses, so misconfiguration surfaces at startup.
        if not os.path.isfile(self._legacy_path):
            raise ProviderUnavailable(LEGACY_KEY_ID, LEGACY_VERSION, "key file missing")
        try:
            _load_private(self._legacy_path)
        except ValueError as exc:
            raise ProviderUnavailable(LEGACY_KEY_ID, LEGACY_VERSION,
                                      f"unusable key material ({exc.__class__.__name__})")

    # called by KeyManager when versioned layout is in use
    def use_versioned_dir(self, keys_dir: str) -> "FileSigningProvider":
        self._versioned_dir = keys_dir
        return self

    def _path_for(self, ref: KeyRef) -> str:
        if ref.version == LEGACY_VERSION:
            return self._legacy_path
        if self._versioned_dir:
            return os.path.join(self._versioned_dir, ref.key_id, f"v{ref.version}.key")
        raise KeyNotFound(ref.key_id, ref.version, "no versioned layout configured")

    def sign_message(self, key_ref: KeyRef, message: bytes) -> bytes:
        key = self._priv_cache.get(key_ref)
        if key is None:
            path = self._path_for(key_ref)
            try:
                key = _load_private(path)
            except FileNotFoundError:
                raise KeyNotFound(key_ref.key_id, key_ref.version, "key file missing")
            except ValueError as exc:
                # message says WHY without echoing content
                raise ProviderUnavailable(key_ref.key_id, key_ref.version,
                                          f"unusable key material ({exc.__class__.__name__})")
            self._priv_cache[key_ref] = key
        return key.sign(message)

    def public_key(self, key_ref: KeyRef) -> Ed25519PublicKey:
        pub = self._pub_cache.get(key_ref)
        if pub is not None:
            return pub
        priv = self._priv_cache.get(key_ref)
        if priv is None:
            path = self._path_for(key_ref)
            try:
                priv = _load_private(path)
            except FileNotFoundError:
                raise KeyNotFound(key_ref.key_id, key_ref.version, "key file missing")
            except ValueError as exc:
                raise ProviderUnavailable(key_ref.key_id, key_ref.version,
                                          f"unusable key material ({exc.__class__.__name__})")
            self._priv_cache[key_ref] = priv
        pub = priv.public_key()
        self._pub_cache[key_ref] = pub
        return pub
