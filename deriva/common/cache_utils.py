"""
Common caching utilities for Deriva.

Provides a base class for disk caching using lmdb (a memory-mapped key-value
store) and utilities for generating cache keys. Used by LLM cache, graph cache,
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
import os
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import lmdb

from deriva.common.exceptions import CacheError
from deriva.common.paths import resolve


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


_MISSING = object()

# lmdb opens a folder once per process: every store on one folder shares its environment,
# which closes when the last of them does (folder -> environment and the number of open stores)
_ENVIRONMENTS: dict[str, tuple[Any, int]] = {}
_ENVIRONMENTS_LOCK = threading.Lock()


def _open_environment(directory: Path, map_size: int) -> Any:
    key = os.path.normcase(str(directory.resolve()))
    with _ENVIRONMENTS_LOCK:
        env, users = _ENVIRONMENTS.get(key, (None, 0))
        if env is None:
            env = lmdb.open(str(directory), map_size=map_size, subdir=True, max_dbs=2)
        _ENVIRONMENTS[key] = (env, users + 1)
        return env


def _close_environment(directory: Path) -> None:
    key = os.path.normcase(str(directory.resolve()))
    with _ENVIRONMENTS_LOCK:
        env, users = _ENVIRONMENTS.get(key, (None, 0))
        if env is None:
            return
        if users > 1:
            _ENVIRONMENTS[key] = (env, users - 1)
            return
        del _ENVIRONMENTS[key]
        env.close()


class _LmdbStore:
    """A small diskcache-shaped key-value store on lmdb.

    Deriva writes JSON rows only ({"seq", "expires", "value"}), so nothing here ever
    unpickles: a row a cache file contains that is not such JSON raises instead of
    running code. A "meta" database holds the eviction state (a sequence number and
    the total row size), so enforcing the size limit needs no scan of the entries.
    """

    _ENTRIES = b"entries"
    _META = b"meta"
    _STATE = b"state"

    def __init__(self, directory: str | Path, size_limit: int):
        self._dir = Path(directory)
        self._size_limit = size_limit
        # The map grows with the data up to map_size; twice the limit leaves room for one eviction pass
        # (the first store on a folder opens it; later ones share that environment)
        self._env = _open_environment(self._dir, max(2 * size_limit, 64 * 1024 * 1024))
        self._entries = self._env.open_db(self._ENTRIES)
        self._meta = self._env.open_db(self._META)
        self._closed = False

    def _read_state(self, txn) -> dict[str, int]:
        raw = txn.get(self._STATE, db=self._meta)
        return json.loads(raw) if raw is not None else {"seq": 0, "size": 0}

    def _write_state(self, txn, state: dict[str, int]) -> None:
        txn.put(self._STATE, json.dumps(state).encode(), db=self._meta)

    def _evict(self, txn) -> None:
        """Inside a write transaction: drop expired and unreadable rows, then the oldest rows, until the size is within the limit."""
        now = time.time()
        state = self._read_state(txn)
        drop: list[bytes] = []
        live: list[tuple[int, bytes, int]] = []  # (seq, key, row bytes)
        size = 0
        for key, raw in txn.cursor(self._entries):
            row_bytes = len(key) + len(raw)
            try:
                row = json.loads(raw)
                seq, expires = row["seq"], row["expires"]
                expired = expires is not None and expires <= now
            except ValueError, TypeError, KeyError:
                drop.append(key)  # not a row Deriva wrote
                continue
            if expired:
                drop.append(key)
                continue
            live.append((seq, key, row_bytes))
            size += row_bytes
        for key in drop:
            txn.delete(key, db=self._entries)
        if size > self._size_limit:
            live.sort()  # the lowest seq is the oldest row
            for _, key, row_bytes in live:
                if size <= self._size_limit:
                    break
                txn.delete(key, db=self._entries)
                size -= row_bytes
        state["size"] = size
        self._write_state(txn, state)

    def get(self, key: str, default: Any = None) -> Any:
        encoded = key.encode()
        with self._env.begin() as txn:
            raw = txn.get(encoded, db=self._entries)
        if raw is None:
            return default
        row = json.loads(raw)  # a row Deriva did not write raises here, it is never unpickled
        expires = row["expires"]
        if expires is not None and expires <= time.time():
            with self._env.begin(write=True) as txn:
                state = self._read_state(txn)
                if txn.get(encoded, db=self._entries) == raw:  # another process may have replaced the row meanwhile
                    txn.delete(encoded, db=self._entries)
                    state["size"] = max(0, state["size"] - len(encoded) - len(raw))
                    self._write_state(txn, state)
            return default
        return row["value"]

    def set(self, key: str, value: Any, expire: float | None = None) -> None:
        encoded = key.encode()
        expires = time.time() + expire if expire is not None else None
        with self._env.begin(write=True) as txn:
            state = self._read_state(txn)
            old = txn.get(encoded, db=self._entries)
            if old is not None:
                state["size"] = max(0, state["size"] - len(encoded) - len(old))
            state["seq"] += 1
            raw = json.dumps({"seq": state["seq"], "expires": expires, "value": value}).encode()
            txn.put(encoded, raw, db=self._entries)
            state["size"] += len(encoded) + len(raw)
            self._write_state(txn, state)
            if state["size"] > self._size_limit:
                self._evict(txn)

    def delete(self, key: str) -> bool:
        encoded = key.encode()
        with self._env.begin(write=True) as txn:
            raw = txn.get(encoded, db=self._entries)
            if raw is None:
                return False
            txn.delete(encoded, db=self._entries)
            state = self._read_state(txn)
            state["size"] = max(0, state["size"] - len(encoded) - len(raw))
            self._write_state(txn, state)
            return True

    def clear(self) -> None:
        with self._env.begin(write=True) as txn:
            txn.drop(self._entries, delete=False)
            self._write_state(txn, {"seq": 0, "size": 0})

    def iterkeys(self) -> list[str]:
        """The keys of the readable, unexpired entries; a key that is not text at all raises (a cache file changed by someone else)."""
        now = time.time()
        keys = []
        with self._env.begin() as txn:
            for key, raw in txn.cursor(self._entries):
                try:
                    row = json.loads(raw)
                    expires = row["expires"]
                    expired = expires is not None and expires <= now
                except ValueError, TypeError, KeyError:
                    continue  # not a row Deriva wrote; get() refuses it
                if expired:
                    continue
                keys.append(key.decode())
        return keys

    def __len__(self) -> int:
        return len(self.iterkeys())

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def volume(self) -> int:
        """The size of the map file on disk (0 when it cannot be read)."""
        try:
            return os.path.getsize(self._dir / "data.mdb")
        except OSError:
            return 0

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _close_environment(self._dir)


class BaseDiskCache:
    """
    Base class for disk caching using lmdb (a memory-mapped key-value store).

    Provides a generic caching interface that stores entries as JSON rows on
    disk for efficient persistence and retrieval. Includes export functionality
    for auditing.

    Attributes:
        cache_dir: Path to the directory storing cache data
        _cache: _LmdbStore instance

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
        self.cache_dir = resolve(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # JSON rows only; rows Deriva did not write are refused, never unpickled
        self._cache = _LmdbStore(self.cache_dir, size_limit or self.DEFAULT_SIZE_LIMIT)

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

        lmdb keeps no separate memory layer.

        Args:
            cache_key: The cache key

        Returns:
            Cached data dict or None if not found
        """
        return self.get(cache_key)

    def get_from_disk(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached data (alias for get, kept for backward compatibility).

        lmdb stores the rows in one map file, not in individual files.

        Args:
            cache_key: The cache key

        Returns:
            Cached data dict or None if not found
        """
        return self.get(cache_key)

    def set(self, cache_key: str, data: dict[str, Any], expire: float | None = None) -> None:
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
        """Clear the in-memory portion of cache (kept for backward compatibility; lmdb has no separate memory layer)."""

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
                - volume: the map file size on disk
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

        Raises:
            CacheError: If the cache file was changed by someone else
        """
        try:
            return list(self._cache.iterkeys())
        except Exception as e:
            raise CacheError(f"Error reading cache keys: {e}") from e

    def export_to_json(self, output_path: str | Path, include_values: bool = True) -> int:
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
