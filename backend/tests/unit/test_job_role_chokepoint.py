"""create_job refuses a missing role and a role that may not create the job type (MIS-177)."""

import pytest

from lokilinux.services.job_service import JobService


@pytest.mark.asyncio
async def test_create_job_denies_missing_or_insufficient_role(db_session, fake_cache, fake_nats):
    svc = JobService(db_session, fake_cache, fake_nats)
    kwargs = dict(name="x", job_type="CUSTOM_COMMAND", target_servers={"agent_ids": []},
                  parameters={"command": "id"})

    with pytest.raises(PermissionError):
        await svc.create_job(**kwargs, actor_role=None)
    with pytest.raises(PermissionError):
        await svc.create_job(**kwargs, actor_role="VIEWER")
