"""Session cache keys hold a digest of the bearer token, never the token (ROADMAP P2)."""

import hashlib

import pytest

from lokilinux.auth.jwks_validator import get_current_user


@pytest.mark.asyncio
async def test_cached_session_is_looked_up_by_digest(fake_cache):
    token = "secret-session-token"
    user = {"id": "u1", "role": "ADMIN"}
    digest = hashlib.sha256(token.encode()).hexdigest()
    await fake_cache.set_cached(f"ba:session:{digest}", user, ttl=60)

    result = await get_current_user(authorization=f"Bearer {token}", cache=fake_cache)

    assert result == user
    assert all(token not in key for key in fake_cache._store)
