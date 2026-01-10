"""
Caching functionality for LLM responses.
Implements both in-memory (LRU) and persistent (JSON file) caching.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from deriva.common.exceptions import CacheError


class CacheManager:
    """Manages caching of LLM responses with both memory and disk persistence."""

    def __init__(self, cache_dir: str = "./llm_manager/cache"):
        """
        Initialize cache manager.

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def generate_cache_key(
        prompt: str,
        model: str,
        schema: dict[str, Any] | None = None,
        bench_hash: str | None = None,
    ) -> str:
        """
        Generate a unique cache key based on prompt, model, and optional schema.

        Args:
            prompt: The prompt text
            model: The model name
            schema: Optional JSON schema for structured output
            bench_hash: Optional benchmark hash (e.g., "repo:model:run") for
                       per-run cache isolation. When set, cache entries are
                       unique per benchmark run, allowing resume after failures.

        Returns:
            SHA256 hash as cache key
        """
        # Combine all inputs into a single string
        cache_input = f"{prompt}|{model}"
        if schema:
            # Sort schema keys for consistent hashing
            schema_str = json.dumps(schema, sort_keys=True)
            cache_input += f"|{schema_str}"
        if bench_hash:
            # Add benchmark context for per-run cache isolation
            cache_input += f"|bench:{bench_hash}"

        # Generate SHA256 hash
        return hashlib.sha256(cache_input.encode()).hexdigest()

    def get_from_memory(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached response from in-memory cache.

        Args:
            cache_key: The cache key

        Returns:
            Cached data or None if not found
        """
        return self._memory_cache.get(cache_key)

    def get_from_disk(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached response from disk.

        Args:
            cache_key: The cache key

        Returns:
            Cached data or None if not found

        Raises:
            CacheError: If cache file is corrupted
        """
        cache_file = self.cache_dir / f"{cache_key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise CacheError(f"Corrupted cache file: {cache_file}") from e
        except Exception as e:
            raise CacheError(f"Error reading cache file: {e}") from e

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached response, checking memory first, then disk.

        Args:
            cache_key: The cache key

        Returns:
            Cached data or None if not found
        """
        # Check memory cache first
        cached = self.get_from_memory(cache_key)
        if cached:
            return cached

        # Check disk cache
        cached = self.get_from_disk(cache_key)
        if cached:
            # Populate memory cache for faster future access
            self._memory_cache[cache_key] = cached

        return cached

    def set(
        self,
        cache_key: str,
        content: str,
        prompt: str,
        model: str,
        usage: dict[str, int] | None = None,
    ) -> None:
        """
        Store response in both memory and disk cache.

        Args:
            cache_key: The cache key
            content: The response content
            prompt: The original prompt
            model: The model used
            usage: Optional usage statistics

        Raises:
            CacheError: If unable to write to disk
        """
        cached_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        cache_data = {
            "content": content,
            "prompt": prompt,
            "model": model,
            "cache_key": cache_key,
            "cached_at": cached_at,
            "usage": usage,
        }

        # Store in memory
        self._memory_cache[cache_key] = cache_data

        # Store on disk
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            raise CacheError(f"Error writing cache file: {e}") from e

    def clear_memory(self) -> None:
        """Clear the in-memory cache."""
        self._memory_cache.clear()

    def clear_disk(self) -> None:
        """
        Clear all cache files from disk.

        Raises:
            CacheError: If unable to delete cache files
        """
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
        except Exception as e:
            raise CacheError(f"Error clearing disk cache: {e}") from e

    def clear_all(self) -> None:
        """Clear both memory and disk caches."""
        self.clear_memory()
        self.clear_disk()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get statistics about the cache.

        Returns:
            Dictionary with cache statistics
        """
        disk_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in disk_files)

        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": len(disk_files),
            "disk_size_bytes": total_size,
            "disk_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }


# Decorator for caching function results
def cached_llm_call(cache_manager: CacheManager):
    """
    Decorator to cache LLM function calls.

    Args:
        cache_manager: CacheManager instance to use

    Returns:
        Decorator function
    """

    def decorator(func):
        @lru_cache(maxsize=128)
        def wrapper(prompt: str, model: str, schema: str | None = None):
            # Convert schema string back to dict if provided
            schema_dict = json.loads(schema) if schema else None
            cache_key = CacheManager.generate_cache_key(prompt, model, schema_dict)

            # Check cache
            cached = cache_manager.get(cache_key)
            if cached:
                return cached

            # Call function and cache result
            result = func(prompt, model, schema_dict)
            if result and "content" in result:
                cache_manager.set(
                    cache_key, result["content"], prompt, model, result.get("usage")
                )

            return result

        return wrapper

    return decorator
