"""
LokiLinux — Phase C correlation evaluator: weighted signal windows -> incident candidates.

One Redis ZSET per (rule, group): member = signal type, score = timestamp
(ms). Re-adding the SAME member just moves its score — repeat occurrences of
one signal type never inflate the correlation score, which is what stops a
single flapping signal from single-handedly crossing a multi-signal
threshold. Score = sum of weights for DISTINCT member types still inside
the window (ZRANGEBYSCORE, not ZCARD).

Tenant isolation is structural, not a runtime check: tenant_id is part of
group_key, so two tenants' identical (rule, host) never share a window key.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import hashlib
import time

from lokilinux.correlation.suppression import is_suppressed

_LOCK_TTL_SEC = 5


@dataclass
class IncidentCandidate:
    rule: Any
    group_key: str
    member_types: list[str]
    score: int
    root_signal_type: str


def _group_key(rule: Any, tenant_id: str, group_values: dict[str, str]) -> str:
    parts = [str(rule.id), tenant_id] + [group_values.get(k, "") for k in rule.group_by]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _weights_by_type(rule: Any) -> dict[str, int]:
    return {c["signal"]: int(c["weight"]) for c in rule.conditions}


class CorrelationEvaluator:
    def __init__(self, cache: Any) -> None:
        self.cache = cache

    async def on_signal(
        self, rules: list[Any], signal: Any, *, tenant_id: str = "default"
    ) -> list[IncidentCandidate]:
        candidates: list[IncidentCandidate] = []
        for rule in rules:
            weights = _weights_by_type(rule)
            if signal.type not in weights:
                continue
            if is_suppressed(rule.suppressions or [], datetime.now(timezone.utc)):
                continue

            group_values = {"host_id": str(signal.host_id) if signal.host_id else ""}
            group_key = _group_key(rule, tenant_id, group_values)
            window_key = f"corr:{rule.id}:{group_key}"

            now_ms = time.time() * 1000
            await self.cache.zadd(window_key, signal.type, now_ms)
            await self.cache.expire(window_key, rule.window_seconds)

            members = await self.cache.zrangebyscore(
                window_key, now_ms - rule.window_seconds * 1000, now_ms
            )
            distinct_members = sorted(set(members))
            score = sum(weights.get(m, 0) for m in distinct_members)
            if score < rule.threshold_score:
                continue

            lock_key = f"lock:corr:{rule.id}:{group_key}"
            if not await self.cache.set_nx(lock_key, ttl=_LOCK_TTL_SEC):
                continue  # already fired for this window moments ago — redelivery guard

            root_signal_type = max(distinct_members, key=lambda m: weights.get(m, 0))
            candidates.append(IncidentCandidate(
                rule=rule, group_key=group_key, member_types=distinct_members,
                score=score, root_signal_type=root_signal_type,
            ))
        return candidates
