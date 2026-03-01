"""In-memory TTL cache for authenticated credentials."""

from asyncio import Task, Lock
from typing import Any, Dict


class AuthCache:
    """In-memory cache for successfully authenticated credentials.

    Entries are automatically purged after their configured TTL using
    asyncio tasks.  A maximum capacity prevents unbounded growth.
    """

    DEFAULT_MAX_SIZE = 10_000

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE) -> None:
        """Initialise an empty cache with its associated lock.

        :param max_size: Maximum number of entries before eviction.
        """
        self._cache_lock = Lock()
        self._cache: Dict[str, Any] = {}
        self._purge_tasks: Dict[str, Task[None]] = {}
        self._max_size = max_size

    async def _purge_entry(self, key: str, expiry: float) -> None:
        """Remove a cache entry after *expiry* seconds.

        :param key: The cache key to purge.
        :param expiry: Seconds to wait before purging.
        """
        from asyncio import sleep

        await sleep(expiry)

        async with self._cache_lock:
            self._cache.pop(key, None)
            self._purge_tasks.pop(key, None)

    async def put(self, key: str, value: Any, expiry: float) -> Any:
        """Store a value in the cache with an automatic expiry.

        If *key* already exists it is replaced and its purge timer is
        restarted.

        :param key: The cache key.
        :param value: The value to cache.
        :param expiry: Time-to-live in seconds.
        :returns: The cached *value*.
        :rtype: Any
        """
        from asyncio import create_task

        async with self._cache_lock:
            if key in self._cache:
                self._purge_tasks[key].cancel()
                del self._cache[key]
                del self._purge_tasks[key]

            # Evict oldest entries if at capacity
            while len(self._cache) >= self._max_size:
                oldest_key = next(iter(self._cache))
                old_task = self._purge_tasks.pop(oldest_key, None)
                if old_task:
                    old_task.cancel()
                del self._cache[oldest_key]

            tsk = create_task(self._purge_entry(key=key, expiry=expiry))
            self._purge_tasks[key] = tsk
            self._cache[key] = value

        return value

    async def get(self, key: str | None) -> Any | None:
        """Retrieve a value from the cache.

        :param key: The cache key, or ``None``.
        :returns: The cached value, or ``None`` if the key is absent or
            ``None`` was passed.
        :rtype: Any | None
        """
        if key is None:
            return None

        async with self._cache_lock:
            return self._cache.get(key, None)
