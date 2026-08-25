"""Unit tests for services/cert_revocation.py (fail-closed semantics)."""

import asyncio

import pytest

from lokilinux.cache import RedisCache
from lokilinux.services import cert_revocation as cr


class FakeRedis:
    def __init__(self):
        self.sets: dict = {}

    async def sadd(self, key, member):
        members = self.sets.setdefault(key, set())
        before = len(members)
        members.add(member)
        return len(members) - before

    async def srem(self, key, member):
        if member in self.sets.get(key, set()):
            self.sets[key].discard(member)
            return 1
        return 0

    async def sismember(self, key, member):
        return member in self.sets.get(key, set())

    async def smembers(self, key):
        return set(self.sets.get(key, set()))


class DownRedis(FakeRedis):
    async def sismember(self, key, member):
        raise ConnectionError("redis is down")


def cache_with(client) -> RedisCache:
    c = RedisCache("redis://test")
    c._client = client
    return c


def test_normalize_serial():
    assert cr.normalize_serial(255) == "ff"
    assert cr.normalize_serial("0xAB") == "ab"
    with pytest.raises(ValueError):
        cr.normalize_serial("zzz")
    with pytest.raises(ValueError):
        cr.normalize_serial(-1)


def test_revoke_list_unrevoke_roundtrip():
    c = cache_with(FakeRedis())
    asyncio.run(cr.revoke(c, "DEADBEEF"))
    assert "deadbeef" in asyncio.run(cr.list_revoked(c))
    assert asyncio.run(cr.unrevoke(c, 0xDEADBEEF)) is True
    assert asyncio.run(cr.unrevoke(c, "deadbeef")) is False


def test_revoked_certificate_raises():
    c = cache_with(FakeRedis())
    asyncio.run(cr.revoke(c, "aa"))
    with pytest.raises(cr.CertificateRevoked):
        asyncio.run(cr.assert_not_revoked(c, "AA"))


def test_unknown_serial_passes():
    c = cache_with(FakeRedis())
    asyncio.run(cr.assert_not_revoked(c, "bb"))  # no exception


def test_disabled_is_noop_even_if_revoked():
    c = cache_with(FakeRedis())
    asyncio.run(cr.revoke(c, "cc"))
    asyncio.run(cr.assert_not_revoked(c, "cc", enabled=False))


def test_redis_down_fail_closed():
    c = cache_with(DownRedis())
    with pytest.raises(cr.RevocationUnavailable):
        asyncio.run(cr.assert_not_revoked(c, "dd", fail_closed=True))


def test_redis_down_permissive_mode_allows():
    c = cache_with(DownRedis())
    asyncio.run(cr.assert_not_revoked(c, "ee", fail_closed=False))


def test_unparseable_serial_fail_closed():
    c = cache_with(FakeRedis())
    with pytest.raises(cr.RevocationUnavailable):
        asyncio.run(cr.assert_not_revoked(c, "not-a-serial"))
