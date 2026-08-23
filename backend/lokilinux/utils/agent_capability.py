"""
LokiLinux — minimal agent capability gate for Faza 10's native workflow
modules (REBOOT/SERVICE/FILE/WORKFLOW_STEPS in agent/internal/modules/*.go).

There is no version/capability negotiation protocol in the heartbeat today
(HeartbeatResponse carries only pending_jobs/resync_domains) — building one
is out of scope here. This is the narrow substitute that makes native
dispatch safe without it: agent_version is already collected on every
heartbeat (models/agent.py) and was simply never compared to anything.
Compare it against the version these modules first shipped in; anything
unparseable or older falls back to compile-down, which is always correct
regardless of agent version (see workflow_engine.py's module docstring).
"""

# The agent version REBOOT/SERVICE/FILE/WORKFLOW_STEPS job_types first ship
# in. Bump this alongside the actual release that adds them — it is the
# only place this decision lives.
MIN_AGENT_VERSION_NATIVE_MODULES = (0, 36, 0)


def _parse_version(v: str | None) -> tuple[int, int, int] | None:
    if not v:
        return None
    parts = v.strip().lstrip("v").split(".")
    if len(parts) < 2:
        return None
    try:
        nums = [int(p) for p in parts[:3]]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def agent_meets_minimum(agent_version: str | None, minimum: tuple[int, int, int] = MIN_AGENT_VERSION_NATIVE_MODULES) -> bool:
    """None, empty, or unparseable agent_version is treated as "too old" —
    conservative by construction, since the whole point is to never risk a
    native job_type landing on an agent binary that doesn't handle it."""
    parsed = _parse_version(agent_version)
    return parsed is not None and parsed >= minimum
