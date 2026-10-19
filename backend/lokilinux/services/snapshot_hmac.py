"""
LokiLinux — per-agent snapshot signing keys (docs/security/SNAPSHOT_HMAC.md).

The server generates a key for each agent on its first heartbeat. The agent
signs the domains it sends in full, and the compliance service checks those
signatures against the keys stored here. A key goes to the agent on heartbeat
only when the agent reports a different key_id.

Rotation is a service call. It is not exposed as an endpoint yet.
"""

import base64
import secrets

from lokilinux.models.agent import Agent


def _new_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def ensure_key(agent: Agent) -> None:
    """Give an agent its first key. No-op once it has one."""
    if agent.snapshot_hmac_key is None:
        agent.snapshot_hmac_key = _new_key()
        agent.snapshot_hmac_key_id = 1


def rotate(agent: Agent) -> None:
    """Make a new key current and keep the old one for verifying in-flight snapshots."""
    agent.snapshot_hmac_prev_key = agent.snapshot_hmac_key
    agent.snapshot_hmac_prev_key_id = agent.snapshot_hmac_key_id
    agent.snapshot_hmac_key = _new_key()
    agent.snapshot_hmac_key_id = (agent.snapshot_hmac_key_id or 0) + 1


def key_for_agent(agent: Agent, reported_key_id: int) -> dict | None:
    """The key to send back, or None when the agent already has the current one."""
    if agent.snapshot_hmac_key is None or reported_key_id == agent.snapshot_hmac_key_id:
        return None
    return {"key_id": agent.snapshot_hmac_key_id, "key": agent.snapshot_hmac_key}
