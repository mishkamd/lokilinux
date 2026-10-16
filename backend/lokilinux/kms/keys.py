"""KeyManager — key lifecycle and versioning (plan §10/§11).

Layout (under keys_dir):
    {key_id}/v{N}.key        private material, 0600
    {key_id}/metadata.json   {"versions": {"N": "ACTIVE|VERIFY_ONLY|RETIRED"}}

States:
    ACTIVE       exactly one — signs everything new
    VERIFY_ONLY  historical versions; signatures still verify
    RETIRED      verification refused (compromise response)

Rotation never deletes material: old signatures must stay verifiable.
"""

import json
import os
import threading
from typing import Dict, Optional

from lokilinux.kms.errors import KeyNotFound, KeyRetired
from lokilinux.kms.file_provider import FileSigningProvider
from lokilinux.kms.provider import KeyRef


class KeyManager:
    def __init__(self, keys_dir: str, key_id: str = "job-signing"):
        self.keys_dir = keys_dir
        self.key_id = key_id
        self._lock = threading.Lock()

    # ── metadata ──────────────────────────────────────────────────────────────
    @property
    def _meta_path(self) -> str:
        return os.path.join(self.keys_dir, self.key_id, "metadata.json")

    def _read_meta(self) -> Dict[str, str]:
        try:
            with open(self._meta_path) as f:
                return json.load(f).get("versions", {})
        except FileNotFoundError:
            return {}

    def _write_meta(self, versions: Dict[str, str]) -> None:
        os.makedirs(os.path.dirname(self._meta_path), exist_ok=True)
        tmp = self._meta_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"versions": versions}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._meta_path)  # atomic

    # ── queries ───────────────────────────────────────────────────────────────
    def active_version(self) -> Optional[int]:
        for v, state in self._read_meta().items():
            if state == "ACTIVE":
                return int(v)
        return None

    def state_of(self, version: int) -> Optional[str]:
        return self._read_meta().get(str(version))

    def versions(self) -> Dict[str, str]:
        """All known versions -> state, e.g. {"1": "VERIFY_ONLY", "2": "ACTIVE"}."""
        return self._read_meta()

    def ref(self, version: int) -> KeyRef:
        return KeyRef(self.key_id, version)

    def active_ref(self) -> KeyRef:
        v = self.active_version()
        if v is None:
            raise KeyNotFound(self.key_id, None, "no ACTIVE version")
        return self.ref(v)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def create(self, version: int, write_key_file=None) -> KeyRef:
        """Registers a new version. `write_key_file(path)` lets the caller
        place material (generation stays outside this class so a future KMS
        provider can generate remotely)."""
        with self._lock:
            meta = self._read_meta()
            if str(version) in meta:
                raise KMSError_Duplicate(self.key_id, version)
            vdir = os.path.join(self.keys_dir, self.key_id)
            os.makedirs(vdir, exist_ok=True)
            path = os.path.join(vdir, f"v{version}.key")
            if write_key_file is not None:
                write_key_file(path)
                os.chmod(path, 0o600)
            elif not os.path.isfile(path):
                raise KMSError_Duplicate(self.key_id, version)
            meta[str(version)] = "VERIFY_ONLY"  # activation is explicit
            self._write_meta(meta)
            return self.ref(version)

    def activate(self, version: int) -> KeyRef:
        with self._lock:
            meta = self._read_meta()
            if str(version) not in meta:
                raise KeyNotFound(self.key_id, version, "unknown version")
            for k, state in meta.items():
                if state == "ACTIVE":
                    meta[k] = "VERIFY_ONLY"  # old ACTIVE demotes, never deleted
            meta[str(version)] = "ACTIVE"
            self._write_meta(meta)
            return self.ref(version)

    def rotate(self, write_key_file) -> KeyRef:
        """create(next version) + activate it. Old ACTIVE → VERIFY_ONLY."""
        with self._lock:
            current = self.active_version() or 0
        new_ref = self.create(current + 1, write_key_file=write_key_file)
        return self.activate(new_ref.version)

    def retire(self, version: int) -> None:
        with self._lock:
            meta = self._read_meta()
            if str(version) not in meta:
                raise KeyNotFound(self.key_id, version, "unknown version")
            meta[str(version)] = "RETIRED"
            self._write_meta(meta)

    # ── verification policy ───────────────────────────────────────────────────
    def verify_allowed(self, version: int) -> bool:
        return self.state_of(version) in ("ACTIVE", "VERIFY_ONLY")

    def enforce_verify_allowed(self, version: int) -> None:
        if not self.verify_allowed(version):
            raise KeyRetired(self.key_id, version, "key retired — signatures no longer trusted")


class KMSError_Duplicate(Exception):
    def __init__(self, key_id: str, version: int):
        super().__init__(f"kms[{key_id}@{version}]: version already exists")


def get_provider(config: dict) -> FileSigningProvider:
    """Factory from settings-shaped config. External providers plug in here;
    unknown providers fail loudly rather than silently downgrading to file."""
    kind = config.get("provider", "file")
    if kind == "file":
        legacy_path = config.get("file", {}).get(
            "key_path",
            os.environ.get("JOB_SIGNING_KEY_PATH", "/etc/lokilinux/certs/job_signing.key"),
        )
        provider = FileSigningProvider(legacy_path)
        keys_dir = os.environ.get("LOKILINUX_KEYS_DIR", "")
        if keys_dir:
            provider.use_versioned_dir(keys_dir)
        return provider
    raise NotImplementedError(f"kms provider {kind!r} planned — interface is stable")
