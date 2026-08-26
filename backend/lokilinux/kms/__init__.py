"""lokilinux-kms — key management & signing abstraction for the control plane.

JobSigner (services/job_signing.py) depends only on the SigningProvider
protocol; whether the key lives in a file, Vault or an HSM is invisible to
the job pipeline. See docs/security/KMS.md.
"""

from lokilinux.kms.errors import KMSError, KeyNotFound, KeyRetired, ProviderUnavailable
from lokilinux.kms.keys import KeyManager, get_provider
from lokilinux.kms.provider import KeyRef, SigningProvider

__all__ = [
    "KeyRef", "SigningProvider", "KeyManager", "get_provider",
    "KMSError", "KeyNotFound", "KeyRetired", "ProviderUnavailable",
]
