"""
LokiLinux — JetStream stream provisioning for the observability pipeline.

Plain-core NATS subscribe/publish stays the primary delivery mechanism
everywhere in this app (see nats_topics.py) — these three streams exist
purely as a 24h replay/audit buffer, not as the delivery path. Existing
subscribers (plain nc.subscribe) are unaffected: a stream just also
captures anything published on a matching subject.

ensure_streams() is idempotent — safe to call on every startup.
"""

from nats.js.api import RetentionPolicy, StreamConfig
import structlog

logger = structlog.get_logger()

_REPLAY_WINDOW_SEC = 24 * 3600

_STREAM_CONFIGS = [
    StreamConfig(name="EVENTS", subjects=["lokilinux.events.>"], retention=RetentionPolicy.LIMITS, max_age=_REPLAY_WINDOW_SEC),
    StreamConfig(name="SIGNALS", subjects=["lokilinux.signals.>"], retention=RetentionPolicy.LIMITS, max_age=_REPLAY_WINDOW_SEC),
    StreamConfig(name="INCIDENTS", subjects=["lokilinux.incidents.>"], retention=RetentionPolicy.LIMITS, max_age=_REPLAY_WINDOW_SEC),
]


async def ensure_streams(nc) -> None:
    js = nc.jetstream()
    for cfg in _STREAM_CONFIGS:
        try:
            await js.add_stream(cfg)
        except Exception:
            try:
                await js.update_stream(cfg)
            except Exception:
                logger.error("eventbus.stream_provision_failed", stream=cfg.name, exc_info=True)
                continue
        logger.info("eventbus.stream_ready", stream=cfg.name)
