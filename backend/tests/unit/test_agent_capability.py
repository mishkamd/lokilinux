import pytest

from lokilinux.utils.agent_capability import agent_meets_minimum


@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.36.0", True),
        ("0.36.1", True),
        ("0.37.0", True),
        ("1.0.0", True),
        ("0.35.3", False),
        ("0.35.99", False),
        ("0.9.9", False),
        (None, False),
        ("", False),
        ("garbage", False),
        ("v0.36.0", True),  # leading v is tolerated
        ("0.36", True),  # missing patch defaults to 0
    ],
)
def test_agent_meets_minimum(version, expected):
    assert agent_meets_minimum(version) is expected
