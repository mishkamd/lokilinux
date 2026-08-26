"""Sanitized KMS exceptions — messages carry key_id/version only,
NEVER key material, paths of secrets or provider credentials."""

from typing import Optional


class KMSError(Exception):
    """Base for all key-management failures."""

    def __init__(self, key_id: str, version: Optional[int], reason: str):
        self.key_id = key_id
        self.version = version
        self.reason = reason  # pre-sanitized by raiser
        super().__init__(f"kms[{key_id}@{version if version is not None else '-'}]: {reason}")


class KeyNotFound(KMSError):
    pass


class KeyRetired(KMSError):
    """Signing requested against a RETIRED key — fail closed."""


class ProviderUnavailable(KMSError):
    """Provider backend unreachable/timeout — no fallback is attempted."""
