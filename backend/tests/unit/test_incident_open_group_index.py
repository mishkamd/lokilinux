"""Partial unique index on incidents (migration 049, ROADMAP M5)."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from lokilinux.incidents.models import Incident


def _incident(group_key: str, status: str = "OPEN") -> Incident:
    return Incident(
        tenant_id="default", title="t", type="BRUTE_FORCE", severity="HIGH",
        status=status, group_key=group_key,
    )


@pytest.mark.asyncio
async def test_second_open_incident_for_same_group_is_rejected(db_session):
    group = f"grp-{uuid.uuid4().hex[:8]}"
    db_session.add(_incident(group))
    await db_session.flush()

    db_session.add(_incident(group))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_resolved_incident_does_not_block_a_new_one(db_session):
    group = f"grp-{uuid.uuid4().hex[:8]}"
    db_session.add(_incident(group, status="RESOLVED"))
    await db_session.flush()

    db_session.add(_incident(group))
    await db_session.flush()  # no IntegrityError
