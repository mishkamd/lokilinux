"""
LokiLinux — JobExecutorWorker: NATS consumer for agent job results.

Subscribes to lokilinux.job.result.
Expected message payload:
  {"job_id": str, "agent_id": str, "exit_code": int,
   "stdout": str, "stderr": str, "duration_ms": int}
"""

import json
import logging
from uuid import UUID

from lokilinux.events.publish import emit, is_pipeline_enabled
from lokilinux.nats_topics import JOB_RESULT
from lokilinux.services.job_service import JobService

logger = logging.getLogger(__name__)


class JobExecutorWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache

    async def start(self) -> None:
        await self.nats.subscribe(JOB_RESULT, cb=self._handle_result)
        logger.info("JobExecutorWorker started")

    async def _handle_result(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            async with self.db_factory() as db:
                svc = JobService(db, self.cache, self.nats)
                await svc.complete_job(
                    job_id=UUID(data["job_id"]),
                    agent_id=UUID(data["agent_id"]),
                    exit_code=data["exit_code"],
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    duration_ms=data.get("duration_ms", 0),
                )
                if await is_pipeline_enabled(self.cache, db):
                    exit_code = data["exit_code"]
                    await emit(
                        self.nats, "job",
                        "job.completed" if exit_code == 0 else "job.failed",
                        severity="INFO" if exit_code == 0 else "WARNING",
                        host_id=data["agent_id"],
                        payload={"job_id": data["job_id"], "exit_code": exit_code},
                    )
        except Exception:
            logger.error("Failed to process job result", exc_info=True)
