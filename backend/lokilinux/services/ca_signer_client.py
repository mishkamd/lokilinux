"""Client for the isolated lokilinux-ca-signer service (Unix socket only —
see ca_signer_service.py). api/grpc call this instead of ever touching
ca.key directly; the private key never enters their process."""

import os

import httpx


class CASignerError(Exception):
    """Sanitized — never carries key material, only what failed."""


def _socket_path() -> str:
    return os.environ.get("CA_SIGNER_SOCKET_PATH", "/run/lokilinux/ca-signer/sign.sock")


async def sign_agent_cert(agent_id: str, public_key_pem: str, validity_days: int) -> str:
    """Returns the signed cert PEM. Raises CASignerError on any failure —
    callers never fall back to signing locally."""
    transport = httpx.AsyncHTTPTransport(uds=_socket_path())
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
            resp = await client.post(
                "http://ca-signer/sign",
                json={
                    "agent_id": agent_id,
                    "public_key_pem": public_key_pem,
                    "validity_days": validity_days,
                },
            )
    except httpx.HTTPError as exc:
        raise CASignerError(f"ca-signer unreachable: {exc.__class__.__name__}") from exc

    if resp.status_code != 200:
        raise CASignerError(f"ca-signer rejected request: {resp.status_code}")
    return resp.json()["cert_pem"]
