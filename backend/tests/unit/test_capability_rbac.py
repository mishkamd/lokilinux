"""Unit tests for utils/capability_rbac.py — capability-tiered job RBAC."""

import pytest

from lokilinux.utils.capability_rbac import (
    assert_can_create,
    required_capabilities,
    unauthorized_capabilities,
)


def test_simple_job_type_maps_to_capability():
    assert required_capabilities("SERVICE") == {"SERVICE_CONTROL"}
    assert required_capabilities("ANSIBLE_PLAYBOOK") == {"EXEC_ANSIBLE"}


def test_workflow_steps_union():
    caps = required_capabilities("WORKFLOW_STEPS", {"steps": [
        {"sequence": 1, "type": "ansible"},
        {"sequence": 2, "type": "package"},
        {"sequence": 3, "type": "command"},
    ]})
    assert caps == {"EXEC_ANSIBLE", "PACKAGE_MANAGEMENT", "EXEC_BASH"}


def test_viewer_denied_execution():
    denied = unauthorized_capabilities("VIEWER", ["EXEC_BASH", "READ_SYSTEM"])
    assert denied == ["EXEC_BASH"]


def test_admin_allowed_everything():
    assert unauthorized_capabilities("ADMIN", [
        "EXEC_BASH", "EXEC_ANSIBLE", "PLUGIN_INSTALL",
        "REBOOT_HOST", "SERVICE_CONTROL",
    ]) == []


def test_operator_can_restart_not_deploy_ansible():
    assert unauthorized_capabilities("OPERATOR", ["SERVICE_CONTROL"]) == []
    assert "EXEC_ANSIBLE" in unauthorized_capabilities("OPERATOR", ["EXEC_ANSIBLE"])


def test_unknown_role_denied_all():
    assert unauthorized_capabilities("INTERN", ["READ_SYSTEM"]) == ["READ_SYSTEM"]


def test_assert_raises_with_capability_names():
    with pytest.raises(PermissionError) as exc:
        assert_can_create("OPERATOR", "ANSIBLE_PLAYBOOK")
    assert "EXEC_ANSIBLE" in str(exc.value)


def test_assert_passes_for_matching_role():
    assert_can_create("MANAGER", "REBOOT")
