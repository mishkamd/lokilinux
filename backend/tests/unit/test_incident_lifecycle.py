import pytest

from lokilinux.incidents.lifecycle import IllegalTransition, assert_legal


def test_open_can_move_to_acknowledged_in_progress_or_resolved():
    assert_legal("OPEN", "ACKNOWLEDGED")
    assert_legal("OPEN", "IN_PROGRESS")
    assert_legal("OPEN", "RESOLVED")


def test_resolved_can_close_or_reopen():
    assert_legal("RESOLVED", "CLOSED")
    assert_legal("RESOLVED", "OPEN")


def test_closed_is_terminal():
    with pytest.raises(IllegalTransition):
        assert_legal("CLOSED", "OPEN")
    with pytest.raises(IllegalTransition):
        assert_legal("CLOSED", "RESOLVED")


def test_illegal_transition_raises_value_error():
    """IllegalTransition IS a ValueError — matches the plan's own wording
    ('illegal transition raises ValueError') while being a more specific,
    catchable type."""
    with pytest.raises(ValueError):
        assert_legal("OPEN", "CLOSED")  # must go through RESOLVED first


def test_acknowledged_cannot_go_back_to_open_directly():
    with pytest.raises(IllegalTransition):
        assert_legal("ACKNOWLEDGED", "OPEN")


def test_same_state_is_not_a_legal_transition():
    with pytest.raises(IllegalTransition):
        assert_legal("OPEN", "OPEN")
