import time
import json
from typing import Any, Optional, Dict
from core.logger import get_logger

logger = get_logger(__name__)

class MemoryTTLCache:
    """Fast in-memory TTL cache with dictionary storage and automatic expiry."""
    def __init__(self, default_ttl: int = 60):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        entry = self._cache.get(key)
        if entry:
            if entry["expiry"] > now:
                logger.debug(f"Cache HIT (Memory): {key}")
                return entry["data"]
            else:
                # Expired
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        self._cache[key] = {
            "data": value,
            "expiry": expiry
        }
        logger.debug(f"Cache SET (Memory): {key} (ttl={ttl or self.default_ttl}s)")

    def delete(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()
        logger.info("Memory TTL Cache cleared.")

# Global Cache Instance
cache = MemoryTTLCache(default_ttl=60)
