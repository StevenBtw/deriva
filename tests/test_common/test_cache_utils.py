"""Tests for common.cache_utils module."""

from __future__ import annotations

import json
import pickle

import pytest

from deriva.common.cache_utils import BaseDiskCache, dict_to_hashable, hash_inputs
from deriva.common.exceptions import CacheError


class TestHashInputs:
    """Tests for hash_inputs function."""

    def test_returns_hex_string(self):
        """Should return a 64-character hex string."""
        result = hash_inputs("test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_input_same_hash(self):
        """Should produce consistent hashes for same input."""
        hash1 = hash_inputs("test", "value")
        hash2 = hash_inputs("test", "value")
        assert hash1 == hash2

    def test_different_input_different_hash(self):
        """Should produce different hashes for different input."""
        hash1 = hash_inputs("test", "value1")
        hash2 = hash_inputs("test", "value2")
        assert hash1 != hash2

    def test_handles_dict_input(self):
        """Should handle dict inputs with consistent ordering."""
        hash1 = hash_inputs({"b": 2, "a": 1})
        hash2 = hash_inputs({"a": 1, "b": 2})
        assert hash1 == hash2

    def test_handles_list_input(self):
        """Should handle list inputs."""
        hash1 = hash_inputs([1, 2, 3])
        hash2 = hash_inputs([1, 2, 3])
        assert hash1 == hash2

    def test_handles_none_input(self):
        """Should skip None values."""
        hash1 = hash_inputs("test", None, "value")
        hash2 = hash_inputs("test", "value")
        assert hash1 == hash2

    def test_custom_separator(self):
        """Should use custom separator."""
        hash1 = hash_inputs("a", "b", separator="|")
        hash2 = hash_inputs("a", "b", separator="::")
        assert hash1 != hash2

    def test_handles_nested_dict(self):
        """Should handle nested dictionaries."""
        result = hash_inputs({"outer": {"inner": "value"}})
        assert isinstance(result, str)
        assert len(result) == 64


class TestDictToHashable:
    """Tests for dict_to_hashable function."""

    def test_returns_tuple(self):
        """Should return a tuple."""
        result = dict_to_hashable({"a": 1})
        assert result == (("a", 1),)

    def test_simple_dict(self):
        """Should convert simple dict to tuple."""
        result = dict_to_hashable({"a": 1, "b": 2})
        assert result == (("a", 1), ("b", 2))

    def test_nested_dict(self):
        """Should handle nested dicts."""
        result = dict_to_hashable({"a": {"b": 1}})
        assert result == (("a", (("b", 1),)),)

    def test_dict_with_list(self):
        """Should convert lists to tuples."""
        result = dict_to_hashable({"a": [1, 2, 3]})
        assert result == (("a", (1, 2, 3)),)

    def test_dict_with_list_of_dicts(self):
        """Should handle lists containing dicts."""
        result = dict_to_hashable({"a": [{"b": 1}]})
        expected = (("a", ((("b", 1),),)),)
        assert result == expected

    def test_sorted_keys(self):
        """Should sort dict keys for consistency."""
        result1 = dict_to_hashable({"b": 2, "a": 1})
        result2 = dict_to_hashable({"a": 1, "b": 2})
        assert result1 == result2


class TestBaseDiskCache:
    """Tests for BaseDiskCache class."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a temporary cache for testing."""
        cache = BaseDiskCache(tmp_path / "test_cache")
        yield cache
        cache.close()

    def test_creates_cache_dir(self, tmp_path):
        """Should create cache directory if not exists."""
        cache_dir = tmp_path / "new_cache"
        cache = BaseDiskCache(cache_dir)
        assert cache_dir.exists()
        cache.close()

    def test_set_and_get(self, cache):
        """Should store and retrieve data."""
        cache.set("key1", {"value": "test"})
        result = cache.get("key1")
        assert result == {"value": "test"}

    def test_get_nonexistent_returns_none(self, cache):
        """Should return None for nonexistent key."""
        result = cache.get("nonexistent")
        assert result is None

    def test_get_from_memory(self, cache):
        """Should retrieve from memory (alias for get)."""
        cache.set("key1", {"value": "test"})
        result = cache.get_from_memory("key1")
        assert result == {"value": "test"}

    def test_get_from_disk(self, cache):
        """Should retrieve from disk (alias for get)."""
        cache.set("key1", {"value": "test"})
        result = cache.get_from_disk("key1")
        assert result == {"value": "test"}

    def test_invalidate(self, cache):
        """Should remove entry from cache."""
        cache.set("key1", {"value": "test"})
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_clear_memory(self, cache):
        """Should clear memory cache."""
        cache.set("key1", {"value": "test"})
        cache.clear_memory()
        # Entry should still be retrievable (cull is optimization)
        result = cache.get("key1")
        assert result == {"value": "test"}

    def test_clear_disk(self, cache):
        """Should clear all cache entries."""
        cache.set("key1", {"value": "test1"})
        cache.set("key2", {"value": "test2"})
        cache.clear_disk()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_clear_all(self, cache):
        """Should clear entire cache."""
        cache.set("key1", {"value": "test"})
        cache.clear_all()
        assert cache.get("key1") is None

    def test_get_stats(self, cache):
        """Should return cache statistics."""
        cache.set("key1", {"value": "test"})
        stats = cache.get_stats()

        assert "entries" in stats
        assert "size_bytes" in stats
        assert "size_mb" in stats
        assert "cache_dir" in stats
        assert stats["entries"] >= 1

    def test_keys(self, cache):
        """Should return list of cache keys."""
        cache.set("key1", {"value": "test1"})
        cache.set("key2", {"value": "test2"})
        keys = cache.keys()

        assert "key1" in keys
        assert "key2" in keys

    def test_export_to_json(self, cache, tmp_path):
        """Should export cache to JSON file."""
        cache.set("key1", {"value": "test1"})
        cache.set("key2", {"value": "test2"})

        output_path = tmp_path / "export.json"
        count = cache.export_to_json(output_path)

        assert count == 2
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert data["entry_count"] == 2
        assert len(data["entries"]) == 2

    def test_export_to_json_without_values(self, cache, tmp_path):
        """Should export only keys when include_values=False."""
        cache.set("key1", {"value": "test1"})

        output_path = tmp_path / "export.json"
        cache.export_to_json(output_path, include_values=False)

        with open(output_path) as f:
            data = json.load(f)

        assert "value" not in data["entries"][0]

    def test_export_creates_parent_dirs(self, cache, tmp_path):
        """Should create parent directories for export."""
        output_path = tmp_path / "nested" / "dir" / "export.json"
        cache.set("key1", {"value": "test"})
        cache.export_to_json(output_path)
        assert output_path.exists()

    def test_context_manager(self, tmp_path):
        """Should work as context manager."""
        cache_dir = tmp_path / "ctx_cache"

        with BaseDiskCache(cache_dir) as cache:
            cache.set("key1", {"value": "test"})
            result = cache.get("key1")
            assert result == {"value": "test"}

    def test_set_with_expire(self, cache):
        """Should accept expire parameter."""
        # Just verify it doesn't crash - TTL testing requires time manipulation
        cache.set("key1", {"value": "test"}, expire=3600)
        result = cache.get("key1")
        assert result == {"value": "test"}

    def test_expired_entry_is_a_miss(self, cache):
        """An entry past its TTL is a miss and is not listed."""
        cache.set("key1", {"value": "test"}, expire=-1)

        assert cache.get("key1") is None
        assert cache.keys() == []

    def test_size_limit_evicts_the_oldest_entry(self, tmp_path):
        """Over the size limit, the oldest entry goes first."""
        cache = BaseDiskCache(tmp_path / "sized_cache", size_limit=120)
        cache.set("first", {"value": "x" * 40})
        cache.set("second", {"value": "y" * 40})

        assert cache.get("first") is None
        assert cache.get("second") == {"value": "y" * 40}
        cache.close()

    def test_values_written_by_deriva_still_round_trip(self, cache):
        """A value far bigger than one row stays in the single map file and round-trips."""
        big = {"text": "x" * 70000}
        cache.set("small", {"value": 1})
        cache.set("big", big)

        assert cache.get("small") == {"value": 1}
        assert cache.get("big") == big
        assert sorted(cache.keys()) == ["big", "small"]

    def test_custom_size_limit(self, tmp_path):
        """Should accept custom size limit."""
        cache = BaseDiskCache(tmp_path / "sized_cache", size_limit=1024 * 1024)
        cache.set("key1", {"value": "test"})
        cache.close()

    def test_close_is_safe(self, cache):
        """Should allow multiple close calls."""
        cache.close()
        cache.close()  # Should not raise


class TestBaseDiskCacheErrors:
    """Tests for error handling in BaseDiskCache."""

    def test_get_raises_cache_error_on_corruption(self, tmp_path):
        """Should raise CacheError when cache is corrupted."""
        cache = BaseDiskCache(tmp_path / "test_cache")

        # Mock internal cache to simulate error
        from unittest.mock import patch

        with patch.object(cache, "_cache") as mock_cache:
            mock_cache.get.side_effect = Exception("Corrupted")
            with pytest.raises(CacheError, match="Error reading from cache"):
                cache.get("key1")

        cache.close()

    def test_set_raises_cache_error_on_write_failure(self, tmp_path):
        """Should raise CacheError when write fails."""
        cache = BaseDiskCache(tmp_path / "test_cache")

        from unittest.mock import patch

        with patch.object(cache, "_cache") as mock_cache:
            mock_cache.set.side_effect = Exception("Write failed")
            with pytest.raises(CacheError, match="Error writing to cache"):
                cache.set("key1", {"value": "test"})

        cache.close()

    def test_invalidate_raises_cache_error_on_delete_failure(self, tmp_path):
        """Should raise CacheError when delete fails."""
        cache = BaseDiskCache(tmp_path / "test_cache")

        from unittest.mock import patch

        with patch.object(cache, "_cache") as mock_cache:
            mock_cache.delete.side_effect = Exception("Delete failed")
            with pytest.raises(CacheError, match="Error deleting cache entry"):
                cache.invalidate("key1")

        cache.close()

    def test_clear_disk_raises_cache_error_on_failure(self, tmp_path):
        """Should raise CacheError when clear fails."""
        cache = BaseDiskCache(tmp_path / "test_cache")

        from unittest.mock import patch

        with patch.object(cache, "_cache") as mock_cache:
            mock_cache.clear.side_effect = Exception("Clear failed")
            with pytest.raises(CacheError, match="Error clearing cache"):
                cache.clear_disk()

        cache.close()

    def test_get_stats_handles_volume_error(self, tmp_path):
        """Should handle volume() errors gracefully."""
        cache = BaseDiskCache(tmp_path / "test_cache")

        from unittest.mock import MagicMock

        original_cache = cache._cache
        mock_cache = MagicMock(wraps=original_cache)
        mock_cache.volume.side_effect = Exception("Volume error")
        mock_cache.__len__ = lambda self: 0
        cache._cache = mock_cache

        stats = cache.get_stats()
        assert stats["size_bytes"] == 0

        cache._cache = original_cache
        cache.close()


_UNPICKLED: list[str] = []


def _record_unpickling(marker: str) -> str:
    _UNPICKLED.append(marker)
    return marker


class _Payload:
    """Pickled, it calls _record_unpickling when loaded: stands in for code planted in a cache file."""

    def __reduce__(self):
        return (_record_unpickling, ("unpickled",))


class TestPlantedRowsRefused:
    """A cache file changed by someone else must not run code: Deriva writes JSON rows only, a row that is not such JSON is refused, never unpickled."""

    @staticmethod
    def _plant(cache: BaseDiskCache, key: bytes, payload: bytes) -> None:
        with cache._cache._env.begin(write=True) as txn:
            txn.put(key, payload, db=cache._cache._entries)

    def test_a_value_that_is_not_json_is_refused(self, tmp_path):
        cache = BaseDiskCache(tmp_path / "planted")
        cache.set("key1", {"value": "test"})
        self._plant(cache, b"key1", pickle.dumps(_Payload()))
        _UNPICKLED.clear()

        with pytest.raises(CacheError):
            cache.get("key1")

        assert _UNPICKLED == []
        cache.close()

    def test_a_key_that_is_not_text_is_refused(self, tmp_path):
        cache = BaseDiskCache(tmp_path / "planted")
        cache.set("key1", {"value": "test"})
        self._plant(cache, pickle.dumps(_Payload()), b'{"seq": 1, "expires": null, "value": 1}')
        _UNPICKLED.clear()

        with pytest.raises(CacheError):
            cache.keys()

        assert _UNPICKLED == []
        cache.close()


def test_two_caches_on_one_folder_share_it(tmp_path):
    """lmdb opens a folder once per process: a second cache there (a benchmark's reading and non-reading
    LLM managers) uses the same store, and closing one leaves the other working."""
    from deriva.common.cache_utils import BaseDiskCache

    first = BaseDiskCache(tmp_path / "shared")
    second = BaseDiskCache(tmp_path / "shared")
    first.set("k", {"answer": 1})

    assert second.get("k") == {"answer": 1}
    first.close()
    second.set("j", {"answer": 2})
    assert second.get("j") == {"answer": 2}
    second.close()
    assert BaseDiskCache(tmp_path / "shared").get("j") == {"answer": 2}
