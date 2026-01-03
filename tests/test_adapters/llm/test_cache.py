"""Tests for managers.llm.cache module."""

import shutil
import tempfile
from pathlib import Path

import pytest

from deriva.adapters.llm.cache import CacheManager
from deriva.adapters.llm.models import CacheError


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

    def test_set_and_get_from_memory(self, cache_manager):
        """Should store and retrieve from memory cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "response content", "test", "gpt-4")

        cached = cache_manager.get_from_memory(cache_key)
        assert cached is not None
        assert cached["content"] == "response content"
        assert cached["model"] == "gpt-4"

    def test_set_and_get_from_disk(self, cache_manager):
        """Should store and retrieve from disk cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "disk content", "test", "gpt-4")

        # Clear memory to force disk read
        cache_manager.clear_memory()

        cached = cache_manager.get_from_disk(cache_key)
        assert cached is not None
        assert cached["content"] == "disk content"

    def test_get_checks_memory_first_then_disk(self, cache_manager):
        """Should check memory cache first, then disk."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "original content", "test", "gpt-4")

        # Clear memory
        cache_manager.clear_memory()
        assert cache_manager.get_from_memory(cache_key) is None

        # get() should load from disk and populate memory
        cached = cache_manager.get(cache_key)
        assert cached is not None
        assert cached["content"] == "original content"

        # Now it should be in memory
        assert cache_manager.get_from_memory(cache_key) is not None

    def test_get_returns_none_for_missing_key(self, cache_manager):
        """Should return None for non-existent cache key."""
        cached = cache_manager.get("nonexistent_key")
        assert cached is None

    def test_clear_memory(self, cache_manager):
        """Should clear memory cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "content", "test", "gpt-4")

        assert cache_manager.get_from_memory(cache_key) is not None

        cache_manager.clear_memory()
        assert cache_manager.get_from_memory(cache_key) is None

    def test_clear_disk(self, cache_manager, temp_cache_dir):
        """Should clear disk cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "content", "test", "gpt-4")

        # Verify file exists
        cache_files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(cache_files) == 1

        cache_manager.clear_disk()

        # Verify file is deleted
        cache_files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(cache_files) == 0

    def test_clear_all(self, cache_manager, temp_cache_dir):
        """Should clear both memory and disk cache."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "content", "test", "gpt-4")

        cache_manager.clear_all()

        assert cache_manager.get_from_memory(cache_key) is None
        assert len(list(Path(temp_cache_dir).glob("*.json"))) == 0

    def test_get_cache_stats(self, cache_manager, temp_cache_dir):
        """Should return accurate cache statistics."""
        # Add some cache entries
        for i in range(3):
            key = CacheManager.generate_cache_key(f"test{i}", "gpt-4")
            cache_manager.set(key, f"content {i}", f"test{i}", "gpt-4")

        stats = cache_manager.get_cache_stats()

        assert stats["memory_entries"] == 3
        assert stats["disk_entries"] == 3
        assert stats["disk_size_bytes"] > 0
        assert stats["cache_dir"] == temp_cache_dir

    def test_cache_with_usage_data(self, cache_manager):
        """Should store and retrieve usage data."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        usage = {"prompt_tokens": 100, "completion_tokens": 50}

        cache_manager.set(cache_key, "content", "test", "gpt-4", usage)

        cached = cache_manager.get(cache_key)
        assert cached["usage"] == usage

    def test_cache_includes_timestamp(self, cache_manager):
        """Should include cached_at timestamp."""
        cache_key = CacheManager.generate_cache_key("test", "gpt-4")
        cache_manager.set(cache_key, "content", "test", "gpt-4")

        cached = cache_manager.get(cache_key)
        assert "cached_at" in cached
        assert cached["cached_at"] is not None


class TestCacheManagerCorruptedCache:
    """Tests for handling corrupted cache files."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_corrupted_cache_file_raises_error(self, temp_cache_dir):
        """Should raise CacheError for corrupted cache file."""
        cache_manager = CacheManager(temp_cache_dir)

        # Create corrupted cache file
        cache_key = "corrupted_key"
        cache_file = Path(temp_cache_dir) / f"{cache_key}.json"
        cache_file.write_text("not valid json {{{")

        with pytest.raises(CacheError) as exc_info:
            cache_manager.get_from_disk(cache_key)

        assert "Corrupted cache file" in str(exc_info.value)


class TestCacheManagerErrors:
    """Tests for error handling in CacheManager."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_from_disk_generic_error(self, temp_cache_dir):
        """Should raise CacheError for generic read errors."""
        from unittest.mock import patch

        cache_manager = CacheManager(temp_cache_dir)

        # Create a valid cache file first
        cache_key = "test_key"
        cache_file = Path(temp_cache_dir) / f"{cache_key}.json"
        cache_file.write_text('{"content": "test"}')

        # Mock open to raise a generic exception
        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            with pytest.raises(CacheError) as exc_info:
                cache_manager.get_from_disk(cache_key)

            assert "Error reading cache file" in str(exc_info.value)

    def test_set_write_error(self, temp_cache_dir):
        """Should raise CacheError when write fails."""
        from unittest.mock import patch

        cache_manager = CacheManager(temp_cache_dir)

        # Mock open to raise exception during write
        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            with pytest.raises(CacheError) as exc_info:
                cache_manager.set("key", "content", "prompt", "model")

            assert "Error writing cache file" in str(exc_info.value)

    def test_clear_disk_error(self, temp_cache_dir):
        """Should raise CacheError when delete fails."""
        from unittest.mock import patch

        cache_manager = CacheManager(temp_cache_dir)

        # Add a cache entry
        cache_manager.set("key", "content", "prompt", "model")

        # Mock unlink to fail
        with patch.object(Path, "unlink", side_effect=PermissionError("Access denied")):
            with pytest.raises(CacheError) as exc_info:
                cache_manager.clear_disk()

            assert "Error clearing disk cache" in str(exc_info.value)


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
