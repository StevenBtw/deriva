"""Tests for managers.llm.cache module."""

import shutil
import tempfile
from pathlib import Path

import pytest

from deriva.adapters.llm.cache import CacheManager


class TestCacheManager:
    """Tests for CacheManager class."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def cache_manager(self, temp_cache_dir):
        """Create a CacheManager with temporary directory."""
        return CacheManager(temp_cache_dir)

    def test_generate_cache_key_consistent(self):
        """Should generate consistent cache keys for same input."""
        key1 = CacheManager.generate_cache_key("test prompt", "gpt-4")
        key2 = CacheManager.generate_cache_key("test prompt", "gpt-4")
        assert key1 == key2

    def test_generate_cache_key_different_prompts(self):
        """Should generate different keys for different prompts."""
        key1 = CacheManager.generate_cache_key("prompt 1", "gpt-4")
        key2 = CacheManager.generate_cache_key("prompt 2", "gpt-4")
        assert key1 != key2

    def test_generate_cache_key_different_models(self):
        """Should generate different keys for different models."""
        key1 = CacheManager.generate_cache_key("test", "gpt-4")
        key2 = CacheManager.generate_cache_key("test", "gpt-3.5")
        assert key1 != key2

    def test_generate_cache_key_with_schema(self):
        """Should include schema in cache key generation."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        key1 = CacheManager.generate_cache_key("test", "gpt-4", schema)
        key2 = CacheManager.generate_cache_key("test", "gpt-4", None)
        assert key1 != key2

    def test_generate_cache_key_with_bench_hash(self):
        """Should include bench_hash in cache key generation."""
        key1 = CacheManager.generate_cache_key("test", "gpt-4", bench_hash="repo:model:1")
        key2 = CacheManager.generate_cache_key("test", "gpt-4", bench_hash="repo:model:2")
        key3 = CacheManager.generate_cache_key("test", "gpt-4", bench_hash=None)
        assert key1 != key2
        assert key1 != key3

    def test_set_and_get(self, cache_manager):
        """Should store and retrieve from cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "response content", "test", "gpt-4")

        cached = cache_manager.get(cache_key)
        assert cached is not None
        assert cached["content"] == "response content"
        assert cached["model"] == "gpt-4"

    def test_get_from_memory_alias(self, cache_manager):
        """get_from_memory should work as alias for get (backward compat)."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "response content", "test", "gpt-4")

        cached = cache_manager.get_from_memory(cache_key)
        assert cached is not None
        assert cached["content"] == "response content"

    def test_get_from_disk_alias(self, cache_manager):
        """get_from_disk should work as alias for get (backward compat)."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "disk content", "test", "gpt-4")

        cached = cache_manager.get_from_disk(cache_key)
        assert cached is not None
        assert cached["content"] == "disk content"

    def test_get_returns_none_for_missing_key(self, cache_manager):
        """Should return None for non-existent cache key."""
        cached = cache_manager.get("nonexistent_key")
        assert cached is None

    def test_clear_all(self, cache_manager):
        """Should clear all cache entries."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "content", "test", "gpt-4")

        # Verify entry exists
        assert cache_manager.get(cache_key) is not None

        cache_manager.clear_all()

        # Entry should be gone
        assert cache_manager.get(cache_key) is None

    def test_clear_disk(self, cache_manager):
        """Should clear all disk cache entries."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "content", "test", "gpt-4")

        # Verify entry exists
        stats_before = cache_manager.get_cache_stats()
        assert stats_before["entries"] >= 1

        cache_manager.clear_disk()

        # All entries should be gone
        stats_after = cache_manager.get_cache_stats()
        assert stats_after["entries"] == 0

    def test_get_cache_stats(self, cache_manager, temp_cache_dir):
        """Should return accurate cache statistics."""
        # Add some cache entries
        for i in range(3):
            key = CacheManager.generate_cache_key(f"test{i}", "gpt-4")
            cache_manager.set_response(key, f"content {i}", f"test{i}", "gpt-4")

        stats = cache_manager.get_cache_stats()

        assert stats["entries"] == 3
        assert stats["memory_entries"] == 3  # Backward compat
        assert stats["disk_entries"] == 3  # Backward compat
        assert stats["size_bytes"] > 0
        assert stats["cache_dir"] == temp_cache_dir

    def test_cache_with_usage_data(self, cache_manager):
        """Should store and retrieve usage data."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        usage = {"prompt_tokens": 100, "completion_tokens": 50}

        cache_manager.set_response(cache_key, "content", "test", "gpt-4", usage)

        cached = cache_manager.get(cache_key)
        assert cached["usage"] == usage

    def test_cache_includes_timestamp(self, cache_manager):
        """Should include cached_at timestamp."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "content", "test", "gpt-4")

        cached = cache_manager.get(cache_key)
        assert "cached_at" in cached
        assert cached["cached_at"] is not None

    def test_invalidate(self, cache_manager):
        """Should remove specific cache entry."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(cache_key, "content", "test", "gpt-4")

        # Verify it exists
        assert cache_manager.get(cache_key) is not None

        # Invalidate
        cache_manager.invalidate(cache_key)

        # Should be gone
        assert cache_manager.get(cache_key) is None

    def test_keys(self, cache_manager):
        """Should return all cache keys."""
        keys_to_add = []
        for i in range(3):
            key = CacheManager.generate_cache_key(f"test{i}", "gpt-4")
            keys_to_add.append(key)
            cache_manager.set_response(key, f"content {i}", f"test{i}", "gpt-4")

        stored_keys = cache_manager.keys()
        assert len(stored_keys) == 3
        for key in keys_to_add:
            assert key in stored_keys


class TestCacheManagerExport:
    """Tests for cache export functionality."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_export_to_json(self, temp_cache_dir):
        """Should export cache contents to JSON."""
        import json

        cache_manager = CacheManager(temp_cache_dir)

        # Add some entries
        for i in range(3):
            key = CacheManager.generate_cache_key(f"test{i}", "gpt-4")
            cache_manager.set_response(key, f"content {i}", f"test{i}", "gpt-4")

        # Export
        export_path = Path(temp_cache_dir) / "export.json"
        count = cache_manager.export_to_json(export_path)

        assert count == 3
        assert export_path.exists()

        # Verify JSON contents
        with open(export_path) as f:
            data = json.load(f)

        assert data["entry_count"] == 3
        assert len(data["entries"]) == 3
        assert all("key" in entry for entry in data["entries"])
        assert all("value" in entry for entry in data["entries"])

    def test_export_keys_only(self, temp_cache_dir):
        """Should export only keys when include_values=False."""
        import json

        cache_manager = CacheManager(temp_cache_dir)
        key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set_response(key, "content", "test", "gpt-4")

        export_path = Path(temp_cache_dir) / "keys_only.json"
        cache_manager.export_to_json(export_path, include_values=False)

        with open(export_path) as f:
            data = json.load(f)

        assert "value" not in data["entries"][0]


class TestCachedLLMCallDecorator:
    """Tests for the cached_llm_call decorator."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_decorator_caches_result(self, temp_cache_dir):
        """Should cache function results."""
        from deriva.adapters.llm.cache import cached_llm_call

        cache_manager = CacheManager(temp_cache_dir)
        call_count = {"count": 0}

        @cached_llm_call(cache_manager)
        def mock_llm_call(prompt: str, model: str, schema=None):
            call_count["count"] += 1
            return {"content": f"Response to: {prompt}"}

        # First call should execute function
        result1 = mock_llm_call("test prompt", "gpt-4")
        assert result1["content"] == "Response to: test prompt"
        assert call_count["count"] == 1

        # Second call with same params should use lru_cache
        result2 = mock_llm_call("test prompt", "gpt-4")
        assert result2["content"] == "Response to: test prompt"
        # lru_cache will prevent actual function call
        assert call_count["count"] == 1

    def test_decorator_uses_cache_manager(self, temp_cache_dir):
        """Should store results in cache manager."""
        from deriva.adapters.llm.cache import cached_llm_call

        cache_manager = CacheManager(temp_cache_dir)

        @cached_llm_call(cache_manager)
        def mock_llm_call(prompt: str, model: str, schema=None):
            return {"content": "cached content", "usage": {"tokens": 10}}

        # Call function
        mock_llm_call("test prompt", "gpt-4")

        # Verify cache manager has the entry
        cache_key = CacheManager.generate_cache_key("test prompt", "gpt-4", None)
        cached = cache_manager.get(cache_key)
        assert cached is not None
        assert cached["content"] == "cached content"

    def test_decorator_with_schema(self, temp_cache_dir):
        """Should include schema in cache key."""
        import json

        from deriva.adapters.llm.cache import cached_llm_call

        cache_manager = CacheManager(temp_cache_dir)

        @cached_llm_call(cache_manager)
        def mock_llm_call(prompt: str, model: str, schema=None):
            return {"content": f"schema: {schema}"}

        schema = {"type": "object"}
        result = mock_llm_call("test", "gpt-4", json.dumps(schema))

        assert "schema:" in result["content"]

    def test_decorator_handles_no_content(self, temp_cache_dir):
        """Should not cache results without content key."""
        from deriva.adapters.llm.cache import cached_llm_call

        cache_manager = CacheManager(temp_cache_dir)

        @cached_llm_call(cache_manager)
        def mock_llm_call(prompt: str, model: str, schema=None):
            return {"error": "something went wrong"}  # No content key

        result = mock_llm_call("test", "gpt-4")
        assert result == {"error": "something went wrong"}

        # Should not be cached (no content key)
        cache_key = CacheManager.generate_cache_key("test", "gpt-4", None)
        cached = cache_manager.get(cache_key)
        assert cached is None


class TestCacheKeyCoversResponseShapingInputs:
    """Everything that shapes the LLM response is part of the key, so changing it never serves a stale answer."""

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ({"system_prompt": "one"}, {"system_prompt": "two"}),
            ({"system_prompt": "one"}, {}),
            ({"temperature": 0.0}, {"temperature": 0.7}),
            ({"max_tokens": 1000}, {"max_tokens": 4000}),
        ],
    )
    def test_different_inputs_give_different_keys(self, a, b):
        assert CacheManager.generate_cache_key("p", "m", **a) != CacheManager.generate_cache_key("p", "m", **b)

    def test_same_inputs_give_the_same_key(self):
        kwargs = {"system_prompt": "s", "temperature": 0.3, "max_tokens": 4000}

        assert CacheManager.generate_cache_key("p", "m", **kwargs) == CacheManager.generate_cache_key("p", "m", **kwargs)
