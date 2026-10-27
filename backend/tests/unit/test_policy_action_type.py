"""PolicyAction.type only takes job types POST /jobs accepts (MIS-177)."""

import pytest
from pydantic import ValidationError

from lokilinux.schemas.policy import PolicyAction


def test_unknown_action_type_is_rejected():
    with pytest.raises(ValidationError):
        PolicyAction(type="HEARTBEAT")


def test_known_action_type_is_accepted():
    assert PolicyAction(type="PACKAGE_UPDATE", params={}).type == "PACKAGE_UPDATE"
