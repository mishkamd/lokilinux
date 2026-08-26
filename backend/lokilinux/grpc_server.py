"""gRPC server bootstrap — JSON codec matching Go agent's jsonCodec."""
import asyncio
import json
import logging
import os
from types import SimpleNamespace

import grpc
import grpc.aio
import nats

from lokilinux.api.grpc.agent_service import AgentServicer
from lokilinux.cache import RedisCache
from lokilinux.db import build_engine, build_session_factory

logger = logging.getLogger(__name__)


def _from_json(data: bytes) -> SimpleNamespace:
    return json.loads(data, object_hook=lambda d: SimpleNamespace(**d))


def _to_json(obj: object) -> bytes:
    if isinstance(obj, dict):
        return json.dumps(obj).encode()
    return json.dumps(obj).encode()


class _AgentServiceHandler(grpc.GenericRpcHandler):
    def __init__(self, servicer: AgentServicer) -> None:
        self._servicer = servicer

    def service_name(self) -> str:
        return "lokilinux.AgentService"

    def service(self, handler_call_details: grpc.HandlerCallDetails):  # type: ignore[override]
        if "HeartbeatStream" in handler_call_details.method:
            return grpc.stream_stream_rpc_method_handler(
                self._servicer.HeartbeatStream,
                request_deserializer=_from_json,
                response_serializer=_to_json,
            )
        return None


async def serve() -> None:
    port = int(os.getenv("GRPC_PORT", "50051"))
    db_url = os.getenv("DATABASE_URL", "")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")

    ca_cert_path = os.getenv("CA_CERT_PATH", "/etc/lokilinux/certs/ca.crt")
    server_cert_path = os.getenv("SERVER_CERT_PATH", "/etc/lokilinux/certs/server.crt")
    server_key_path = os.getenv("SERVER_KEY_PATH", "/etc/lokilinux/certs/server.key")

    engine = build_engine(db_url)
    session_factory = build_session_factory(engine)

    cache = RedisCache(url=redis_url)
    await cache.connect()

    nc = await nats.connect(nats_url)

    servicer = AgentServicer(db_factory=session_factory, cache=cache, nats=nc)

    with open(server_key_path, "rb") as f:
        server_key = f.read()
    with open(server_cert_path, "rb") as f:
        server_cert = f.read()
    with open(ca_cert_path, "rb") as f:
        ca_cert = f.read()

    credentials = grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=True,
    )

    server = grpc.aio.server(
        options=[
            ("grpc.max_recv_message_length", 16 * 1024 * 1024),
            ("grpc.max_send_message_length", 16 * 1024 * 1024),
        ]
    )
    server.add_generic_rpc_handlers([_AgentServiceHandler(servicer)])
    server.add_secure_port(f"[::]:{port}", credentials)

    if os.environ.get("METRICS_ENABLED", "true").lower() == "true":
        from lokilinux.metrics import start_metrics_server

        start_metrics_server(int(os.environ.get("METRICS_PORT", "9091")))

    logger.info("grpc.start port=%d", port)
    await server.start()

    try:
        await server.wait_for_termination()
    finally:
        await nc.drain()
        await cache.disconnect()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
