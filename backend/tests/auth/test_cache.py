"""Tests for AuthCache."""

import pytest
import asyncio

from auth.cache import AuthCache


class ConcreteCache(AuthCache):
    """Concrete implementation for testing."""

    pass


@pytest.mark.asyncio
async def test_put_and_get() -> None:
    """Verify a stored key can be retrieved before expiry."""
    cache = ConcreteCache()
    await cache.put("key1", "value1", expiry=10.0)
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_get_missing_key() -> None:
    """Verify ``get`` returns ``None`` for an absent key."""
    cache = ConcreteCache()
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_none_key() -> None:
    """Verify ``get`` returns ``None`` when *key* is ``None``."""
    cache = ConcreteCache()
    result = await cache.get(None)
    assert result is None


@pytest.mark.asyncio
async def test_put_overwrite() -> None:
    """Verify a second ``put`` overwrites the previous value."""
    cache = ConcreteCache()
    await cache.put("key1", "value1", expiry=10.0)
    await cache.put("key1", "value2", expiry=10.0)
    result = await cache.get("key1")
    assert result == "value2"


@pytest.mark.asyncio
async def test_expiry() -> None:
    """Verify entries are evicted after their TTL elapses."""
    cache = ConcreteCache()
    await cache.put("expiring", "data", expiry=0.1)
    result = await cache.get("expiring")
    assert result == "data"

    await asyncio.sleep(0.3)
    result = await cache.get("expiring")
    assert result is None
