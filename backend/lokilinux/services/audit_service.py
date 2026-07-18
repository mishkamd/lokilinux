"""
LokiLinux — AuditService: append-only audit log writes and paginated reads.

AuditLog column names: source_ip (not ip_address), changes (not payload),
timestamp (not created_at). user_id is a plain string (Better Auth user ID).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.audit import AuditLog
from lokilinux.schemas.audit import AuditLogResponse


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        action: str,
        user_id: str | None = None,
        actor_type: str = "user",
        actor_name: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        source_ip: str | None = None,
        changes: dict | None = None,
        status: str = "success",
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            actor_type=actor_type,
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            source_ip=source_ip,
            changes=changes,
            status=status,
        )
        self.db.add(entry)
        await self.db.commit()
        return entry

    async def list_logs(self, limit: int = 50, cursor: int | None = None) -> dict:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if cursor is not None:
            q = q.where(AuditLog.id < cursor)
        result = await self.db.execute(q)
        logs = result.scalars().all()
        next_cursor = logs[-1].id if len(logs) == limit else None
        items = [AuditLogResponse.model_validate(log) for log in logs]
        return {"items": items, "next_cursor": next_cursor, "total": len(items)}
