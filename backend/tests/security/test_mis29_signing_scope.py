"""MIS-29 signing scope: with JOB_SIGNING_REQUIRED on and no usable signer, only
privileged job types are held. A non-privileged job goes out with its params
unchanged; a privileged job raises EnvelopeSigningError instead of going unsigned.

Fixtures are local: this module needs no database or cache.
"""

from types import SimpleNamespace

import pytest

from lokilinux import metrics
from lokilinux.services import job_envelope


class _Counter:
    def __init__(self):
        self.n = 0

    def inc(self, amount=1):
        self.n += amount


def _job(job_type):
    return SimpleNamespace(id="j-1", job_type=job_type, agent_id="a-1", tenant_id="", policy_id="")


@pytest.fixture()
def no_signer(monkeypatch, tmp_path):
    """Fresh singleton, no key file, no versioned KMS dir."""
    monkeypatch.setattr(job_envelope, "_signer_instance", None)
    monkeypatch.setattr(job_envelope, "_signer_init_done", False)
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(tmp_path / "missing.key"))
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    monkeypatch.delenv("KMS_PROVIDER", raising=False)
    monkeypatch.delenv("JOB_SIGNING_ENVELOPES", raising=False)
    monkeypatch.delenv("JOB_SIGNING_REQUIRED", raising=False)
    return monkeypatch


def test_non_privileged_job_is_not_held_when_required_and_no_key(no_signer):
    no_signer.setenv("JOB_SIGNING_REQUIRED", "true")
    params = {"path": "/etc"}

    out = job_envelope.maybe_attach_envelope(_job("INVENTORY_SCAN"), params, "0.40.0")

    assert out is params
    assert "_envelope" not in out


def test_privileged_job_is_held_when_required_and_no_key(no_signer):
    no_signer.setenv("JOB_SIGNING_REQUIRED", "true")

    with pytest.raises(job_envelope.EnvelopeSigningError):
        job_envelope.maybe_attach_envelope(_job("SERVICE"), {"service_name": "nginx"}, "0.40.0")


def test_privileged_job_is_held_when_required_and_signer_unusable(no_signer, tmp_path):
    """Key file present, but the versioned KMS provider cannot be built: _get_signer()
    returns None instead of raising. Required mode must still refuse to go unsigned."""
    key = tmp_path / "job_signing.key"
    key.write_bytes(b"not a key")
    no_signer.setenv("JOB_SIGNING_KEY_PATH", str(key))
    no_signer.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))
    no_signer.setenv("KMS_PROVIDER", "vault")
    no_signer.setenv("JOB_SIGNING_REQUIRED", "true")

    with pytest.raises(job_envelope.EnvelopeSigningError):
        job_envelope.maybe_attach_envelope(_job("SERVICE"), {"service_name": "nginx"}, "0.40.0")


def test_unsigned_metric_counts_only_privileged_jobs(no_signer):
    """Flag off, no key: the counter is named for privileged jobs, so only privileged
    jobs that go out unsigned increment it."""
    counter = _Counter()
    no_signer.setattr(metrics, "unsigned_privileged_jobs_total", counter)
    params = {"path": "/etc"}

    assert job_envelope.maybe_attach_envelope(_job("INVENTORY_SCAN"), params, "0.40.0") is params
    assert counter.n == 0

    assert job_envelope.maybe_attach_envelope(_job("SERVICE"), params, "0.40.0") is params
    assert counter.n == 1
