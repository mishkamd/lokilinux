"""Unit tests for the agent policy compiler (Faza 1).

Covers the plan §11 backend matrix rows that live at compile level:
unknown-field rejection, clamp bounds, deny-by-default normalization,
payload size cap, signature roundtrip + tamper rejection.
"""

import base64

import pytest

from lokilinux.services import agent_policy_compiler as compiler
from lokilinux.services.agent_policy_compiler import PolicyValidationError


def _doc(**spec_overrides):
    spec = {"collectors": {"sshd": {"enabled": True}}}
    spec.update(spec_overrides)
    return {
        "apiVersion": "lokilinux.io/v1",
        "kind": "AgentPolicy",
        "metadata": {"name": "test"},
        "spec": spec,
    }


class TestValidate:
    def test_valid_minimal_passes(self):
        out = compiler.validate(_doc())
        assert out["metadata"]["name"] == "test"

    def test_wrong_kind_rejected(self):
        with pytest.raises(PolicyValidationError, match="kind"):
            compiler.validate({"apiVersion": "lokilinux.io/v1", "kind": "Other"})

    def test_unknown_api_version_rejected(self):
        doc = _doc()
        doc["apiVersion"] = "lokilinux.io/v2"
        with pytest.raises(PolicyValidationError, match="apiVersion"):
            compiler.validate(doc)

    def test_missing_name_rejected(self):
        doc = {"apiVersion": "lokilinux.io/v1", "kind": "AgentPolicy", "metadata": {}}
        with pytest.raises(PolicyValidationError, match="name"):
            compiler.validate(doc)

    def test_unknown_spec_field_rejected(self):
        with pytest.raises(PolicyValidationError, match="unknown"):
            compiler.validate(_doc(bogus_section={}))

    def test_unknown_collector_rejected(self):
        with pytest.raises(PolicyValidationError, match="bogus"):
            compiler.validate(_doc(collectors={"bogus": {"enabled": True}}))

    def test_deny_by_default_unlisted_collectors_disabled(self):
        out = compiler.validate(_doc())
        assert out["spec"]["collectors"]["packages"] == {"enabled": False}
        assert out["spec"]["collectors"]["sshd"] == {"enabled": True}

    def test_heartbeat_clamped_to_bounds(self):
        out = compiler.validate(_doc(heartbeat={"interval_seconds": 3}))
        assert out["spec"]["heartbeat"]["interval_seconds"] == 10
        out = compiler.validate(_doc(heartbeat={"interval_seconds": 99999}))
        assert out["spec"]["heartbeat"]["interval_seconds"] == 300

    def test_faza5_runtime_sections_rejected_when_nonempty(self):
        with pytest.raises(PolicyValidationError, match="Faza 5"):
            compiler.validate(_doc(signals={"rules": [{"id": "x"}]}))

    def test_faza5_empty_reserved_sections_allowed_and_stripped(self):
        out = compiler.validate(_doc(compliance={}))
        assert "compliance" not in out["spec"]

    def test_parse_yaml_rejects_garbage(self):
        with pytest.raises(PolicyValidationError, match="invalid YAML"):
            compiler.parse_yaml("a: [::")

    def test_payload_size_cap(self):
        big = "x" * (compiler.MAX_PAYLOAD_BYTES + 1)
        with pytest.raises(PolicyValidationError, match="exceeds"):
            compiler.parse_yaml(f"name: {big}")


class TestSigning:
    def test_sign_verify_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POLICY_SIGNING_KEY_PATH", str(tmp_path / "k.pem"))
        payload = compiler.validate(_doc())
        sig = compiler.sign_payload(payload)
        assert compiler.verify_signature(payload, sig, compiler.public_key_b64())

    def test_tampered_payload_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POLICY_SIGNING_KEY_PATH", str(tmp_path / "k.pem"))
        payload = compiler.validate(_doc())
        sig = compiler.sign_payload(payload)
        tampered = dict(payload)
        tampered["metadata"] = {"name": "evil"}
        assert not compiler.verify_signature(tampered, sig, compiler.public_key_b64())

    def test_signature_is_base64_ed25519(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POLICY_SIGNING_KEY_PATH", str(tmp_path / "k.pem"))
        sig = base64.b64decode(compiler.sign_payload(compiler.validate(_doc())))
        assert len(sig) == 64  # ed25519 signature is always 64 bytes
