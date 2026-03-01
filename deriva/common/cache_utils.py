"""
Common caching utilities for Deriva.

Provides a base class for disk caching using diskcache (SQLite-backed)
and utilities for generating cache keys. Used by LLM cache, graph cache,
and other caching implementations.

Usage:
    from deriva.common.cache_utils import BaseDiskCache, hash_inputs

    class MyCache(BaseDiskCache):
        def generate_key(self, *args) -> str:
            return hash_inputs(*args)
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import diskcache

from deriva.common.exceptions import CacheError


def hash_inputs(*args: Any, separator: str = "|") -> str:
    """
    Generate SHA256 hash from arbitrary inputs.

    Args:
        *args: Values to hash (will be converted to strings)
        separator: Separator between values (default: "|")

    Returns:
        SHA256 hex digest

    Example:
        >>> hash_inputs("prompt", "gpt-4", {"key": "value"})
        'a1b2c3...'  # 64-char hex string
    """
    parts = []
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, dict):
            # Sort dict keys for consistent hashing
            parts.append(json.dumps(arg, sort_keys=True, default=str))
        elif isinstance(arg, (list, tuple)):
            parts.append(json.dumps(arg, sort_keys=True, default=str))
        else:
            parts.append(str(arg))

    combined = separator.join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def dict_to_hashable(d: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """
    Convert a dict to a hashable tuple representation.

    Recursively converts nested dicts and lists to tuples.
    Useful for using dicts as cache keys with @lru_cache.

    Args:
        d: Dictionary to convert

    Returns:
        Nested tuple representation that can be hashed

    Example:
        >>> dict_to_hashable({"a": 1, "b": {"c": 2}})
        (('a', 1), ('b', (('c', 2),)))
    """
    items: list[tuple[str, Any]] = []
    for k, v in sorted(d.items()):
        if isinstance(v, dict):
            items.append((k, dict_to_hashable(v)))
        elif isinstance(v, list):
            # Convert list items recursively
            list_items: list[Any] = []
            for item in v:
                if isinstance(item, dict):
                    list_items.append(dict_to_hashable(item))
                else:
                    list_items.append(item)
            items.append((k, tuple(list_items)))
        else:
            items.append((k, v))
    return tuple(items)


@lru_cache(maxsize=128)
def _hash_dict_tuple(dict_tuple: tuple[tuple[str, Any], ...]) -> str:
    """
    Generate JSON string from a dict tuple (cached for performance).

    This is an internal function used to avoid repeated JSON serialization
    of the same dict structures.

    Args:
        dict_tuple: Tuple from dict_to_hashable()

    Returns:
        JSON string representation
    """

    # Convert back to dict for JSON serialization
    def tuple_to_dict(t: tuple) -> dict | list | Any:
        if isinstance(t, tuple) and len(t) > 0:
            # Check if it's a key-value tuple (dict item)
            if isinstance(t[0], tuple) and len(t[0]) == 2:
                return {k: tuple_to_dict(v) for k, v in t}
            # Check if it's a single key-value pair
            if len(t) == 2 and isinstance(t[0], str):
                return t  # Return as-is, handled by parent
        return t

    result = dict(dict_tuple)
    return json.dumps(result, sort_keys=True)


class BaseDiskCache:
    """
    Base class for disk caching using diskcache (SQLite-backed).

    Provides a generic caching interface that stores entries in SQLite
    for efficient persistence and retrieval. Includes export functionality
    for auditing.

    Attributes:
        cache_dir: Path to the directory storing cache data
        _cache: diskcache.Cache instance

    Example:
        class MyCache(BaseDiskCache):
            def __init__(self):
                super().__init__("./my_cache")

            def get_or_compute(self, key: str, compute_fn) -> Any:
                cached = self.get(key)
                if cached is not None:
                    return cached["data"]
                result = compute_fn()
                self.set(key, {"data": result})
                return result
    """

    # Default size limit: 1GB
    DEFAULT_SIZE_LIMIT = 2**30

    def __init__(self, cache_dir: str | Path, size_limit: int | None = None):
        """
        Initialize cache with specified directory.

        Args:
            cache_dir: Directory to store cache files (created if not exists)
            size_limit: Maximum cache size in bytes (default: 1GB)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize diskcache with JSON serialization (no pickle)
        self._cache = diskcache.Cache(
            str(self.cache_dir),
            size_limit=size_limit or self.DEFAULT_SIZE_LIMIT,
            disk=diskcache.JSONDisk,
            disk_compress_level=0,
        )

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached data.

        Args:
            cache_key: The cache key

        Returns:
            Cached data dict or None if not found

        Raises:
            CacheError: If cache is corrupted
        """
        try:
            result = self._cache.get(cache_key)
            return result
        except Exception as e:
            raise CacheError(f"Error reading from cache: {e}") from e

    def get_from_memory(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached data (alias for get, kept for backward compatibility).

        diskcache handles its own memory caching internally.

        Args:
            cache_key: The cache key

        Returns:
            Cached data dict or None if not found
        """
        return self.get(cache_key)

    def get_from_disk(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached data (alias for get, kept for backward compatibility).

        diskcache uses SQLite, not individual files.

        Args:
            cache_key: The cache key

        Returns:
            Cached data dict or None if not found
        """
        return self.get(cache_key)

    def set(
        self, cache_key: str, data: dict[str, Any], expire: float | None = None
    ) -> None:
        """
        Store data in cache.

        Args:
            cache_key: The cache key
            data: Dictionary to cache
            expire: Optional TTL in seconds

        Raises:
            CacheError: If unable to write to cache
        """
        try:
            self._cache.set(cache_key, data, expire=expire)
        except Exception as e:
            raise CacheError(f"Error writing to cache: {e}") from e

    def invalidate(self, cache_key: str) -> None:
        """
        Remove entry from cache.

        Args:
            cache_key: The cache key to invalidate
        """
        try:
            self._cache.delete(cache_key)
        except Exception as e:
            raise CacheError(f"Error deleting cache entry: {e}") from e

    def clear_memory(self) -> None:
        """Clear the in-memory portion of cache (triggers SQLite cleanup)."""
        try:
            self._cache.cull()
        except Exception:
            pass  # Cull is optional optimization

    def clear_disk(self) -> None:
        """
        Clear all cache entries.

        Raises:
            CacheError: If unable to clear cache
        """
        try:
            self._cache.clear()
        except Exception as e:
            raise CacheError(f"Error clearing cache: {e}") from e

    def clear_all(self) -> None:
        """Clear the entire cache."""
        self.clear_disk()

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about the cache.

        Returns:
            Dictionary with:
                - entries: Number of entries in cache
                - size_bytes: Total size of cache
                - size_mb: Total size in megabytes
                - cache_dir: Path to cache directory
                - volume: diskcache volume stats
        """
        try:
            volume = self._cache.volume()
        except Exception:
            volume = 0

        entry_count = len(self._cache)

        return {
            "memory_entries": entry_count,  # Kept for backward compat
            "disk_entries": entry_count,  # Kept for backward compat
            "entries": entry_count,
            "disk_size_bytes": volume,
            "disk_size_mb": round(volume / (1024 * 1024), 2),
            "size_bytes": volume,
            "size_mb": round(volume / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }

    def keys(self) -> list[str]:
        """
        Get all cache keys.

        Returns:
            List of cache keys
        """
        return list(self._cache.iterkeys())

    def export_to_json(
        self, output_path: str | Path, include_values: bool = True
    ) -> int:
        """
        Export cache contents to JSON for auditing.

        Args:
            output_path: Path to write JSON file
            include_values: If True, include cached values; if False, keys only

        Returns:
            Number of entries exported

        Example:
            cache = BaseDiskCache("./my_cache")
            count = cache.export_to_json("./cache_audit.json")
            print(f"Exported {count} entries")
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        entries = []
        for key in self._cache.iterkeys():
            entry = {"key": key}
            if include_values:
                try:
                    entry["value"] = self._cache[key]
                except KeyError:
                    entry["value"] = None
                    entry["error"] = "Key expired or deleted during export"
            entries.append(entry)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cache_dir": str(self.cache_dir),
                    "entry_count": len(entries),
                    "entries": entries,
                },
                f,
                indent=2,
                default=str,
            )

        return len(entries)

    def close(self) -> None:
        """Close the cache connection."""
        try:
            self._cache.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


__all__ = [
    "BaseDiskCache",
    "hash_inputs",
    "dict_to_hashable",
]
