"""SigningProvider protocol + KeyRef (plan §8/§9).

JobSigner depends ONLY on this protocol. Providers:
  - FileSigningProvider (development / fallback, this repo)
  - Vault / cloud KMS / HSM — future implementations; the interface is the
    contract, no vendor types leak into the job pipeline.

Interface note: Ed25519 signs raw messages (not pre-hashed digests), so the
protocol uses sign_message/public_key instead of a hash-and-sign shape —
same separation of key management vs cryptography, adapted to the algorithm
the platform already standardized.
"""

from dataclasses import dataclass
from typing import Optional
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from lokilinux.kms.errors import KMSError


@dataclass(frozen=True)
class KeyRef:
    key_id: str
    version: int


@runtime_checkable
class SigningProvider(Protocol):
    def sign_message(self, key_ref: KeyRef, message: bytes) -> bytes:
        """Ed25519-sign `message` with the referenced key.
        Raises KMSError subclasses on any failure (never leaks material)."""
        ...

    def public_key(self, key_ref: KeyRef) -> Ed25519PublicKey:
        ...


def raise_sanitized(key_id: str, version: Optional[int], reason: str) -> "KMSError":
    return KMSError(key_id, version, reason)


# re-export for callers that want a single import point
__all__ = ["KeyRef", "SigningProvider", "KMSError", "raise_sanitized"]
