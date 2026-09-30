"""
Caching functionality for LLM responses.

Extends BaseDiskCache with LLM-specific key generation and metadata.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from deriva.common.cache_utils import BaseDiskCache, dict_to_hashable, hash_inputs


# Cache schema hashes to avoid repeated JSON serialization (improves performance)
@lru_cache(maxsize=128)
def _hash_schema(schema_tuple: tuple) -> str:
    """
    Generate a hash for a schema tuple.

    Uses frozen tuple representation since dicts aren't hashable.
    Cached with LRU to avoid re-hashing the same schemas.
    """
    # Convert back to dict for JSON serialization
    schema_dict = dict(schema_tuple)
    return json.dumps(schema_dict, sort_keys=True)


class CacheManager(BaseDiskCache):
    """
    LLM response cache with prompt/model-based key generation.

    Extends BaseDiskCache with LLM-specific functionality:
    - Cache key generation from prompt + model + schema + bench_hash + system prompt + temperature + max_tokens
    - Response metadata storage (usage stats, timestamps)

    Example:
        cache = CacheManager("./llm_cache")
        key = cache.generate_cache_key(prompt, model, schema)
        if cached := cache.get(key):
            return cached["content"]
        # ... call LLM ...
        cache.set_response(key, content, prompt, model, usage)
    """

    def __init__(self, cache_dir: str = "workspace/cache/llm"):
        """
        Initialize LLM cache manager.

        Args:
            cache_dir: Directory to store cache files
        """
        super().__init__(cache_dir)

    @staticmethod
    def generate_cache_key(
        prompt: str,
        model: str,
        schema: dict[str, Any] | None = None,
        bench_hash: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a unique cache key from everything that shapes the response.

        A changed system prompt, temperature or max_tokens must never be served
        an answer cached for different settings.

        Args:
            prompt: The prompt text
            model: The model name
            schema: Optional JSON schema for structured output
            bench_hash: Optional benchmark hash (e.g., "repo:model:run") for
                       per-run cache isolation. When set, cache entries are
                       unique per benchmark run, allowing resume after failures.
            system_prompt: Optional system prompt sent with the prompt
            temperature: Effective sampling temperature of the call
            max_tokens: Effective max_tokens of the call

        Returns:
            SHA256 hash as cache key
        """
        # Build cache input parts
        parts = [prompt, model]

        if schema:
            # Use cached schema hashing for better performance
            schema_tuple = dict_to_hashable(schema)
            schema_str = _hash_schema(schema_tuple)
            parts.append(schema_str)

        if bench_hash:
            # Add benchmark context for per-run cache isolation
            parts.append(f"bench:{bench_hash}")

        if system_prompt:
            parts.append(f"system:{system_prompt}")
        if temperature is not None:
            parts.append(f"temperature:{temperature}")
        if max_tokens is not None:
            parts.append(f"max_tokens:{max_tokens}")

        return hash_inputs(*parts)

    # Inherited from BaseDiskCache:
    # - get_from_memory(cache_key)
    # - get_from_disk(cache_key)
    # - get(cache_key)
    # - clear_memory()
    # - clear_disk()
    # - clear_all()
    # - get_stats()

    def set_response(
        self,
        cache_key: str,
        content: str,
        prompt: str,
        model: str,
        usage: dict[str, int] | None = None,
    ) -> None:
        """
        Store LLM response in cache with metadata.

        This is the LLM-specific setter that includes response metadata.
        Uses the base class set() method for actual storage.

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

        # Use base class set() for storage
        super().set(cache_key, cache_data)

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get statistics about the cache.

        Alias for get_stats() for backward compatibility.

        Returns:
            Dictionary with cache statistics
        """
        return self.get_stats()


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
                cache_manager.set_response(cache_key, result["content"], prompt, model, result.get("usage"))

            return result

        return wrapper

    return decorator
