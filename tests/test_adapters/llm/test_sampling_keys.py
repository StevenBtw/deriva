"""Sampling (k answers to one prompt, combined by majority): each sample has its own cache entry, so a replay votes
over the k answers the run got, not over one answer k times. A single call keeps its key."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import duckdb
import pytest

from deriva.adapters.llm.cache import CacheManager
from deriva.modules.extraction.base import sample_llm
from deriva.services import config


class TestCacheKey:
    def test_each_sample_has_its_own_key(self):
        keys = {CacheManager.generate_cache_key("p", "m", sample=i) for i in range(3)}
        assert len(keys) == 3

    def test_sample_zero_and_a_single_call_share_the_key(self):
        assert CacheManager.generate_cache_key("p", "m", sample=0) == CacheManager.generate_cache_key("p", "m")


class TestSampler:
    def test_samples_are_numbered(self):
        seen = []

        def llm(prompt, schema, **kwargs):
            seen.append(kwargs.get("sample"))
            return kwargs.get("sample")

        assert sample_llm(llm, "p", {}, 3) == [0, 1, 2]
        assert sorted(seen) == [0, 1, 2]

    def test_a_single_call_passes_no_sample(self):
        llm = MagicMock(return_value="a")
        assert sample_llm(llm, "p", {}, 1) == ["a"]
        llm.assert_called_once_with("p", {})


def test_the_session_hands_the_sample_to_the_manager():
    from deriva.services.session import PipelineSession

    session = PipelineSession.__new__(PipelineSession)
    session._llm_manager = MagicMock()
    session._llm_error = None
    session._cancel_check = None
    session._engine = None
    session._record_call = MagicMock()
    query = session._get_llm_query_fn()
    assert query is not None
    query("p", {}, sample=2)
    assert session._llm_manager.query.call_args.kwargs["sample"] == 2


@pytest.fixture
def engine():
    db = duckdb.connect(":memory:")
    db.execute("CREATE TABLE system_settings (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP)")
    yield db
    db.close()


class TestSetting:
    def test_unset_keeps_each_steps_own_samples(self, engine):
        assert config.get_llm_samples(engine) is None
        assert config.effective_samples(engine, 1) == 1
        assert config.effective_samples(engine, 3) == 3

    def test_set_it_applies_to_every_voting_step(self, engine):
        config.set_setting(engine, "llm_samples", "5")
        assert config.effective_samples(engine, 1) == 5

    @pytest.mark.parametrize("value", ["0", "-1", "two", "21"])
    def test_a_sample_count_is_1_to_20(self, engine, value):
        with pytest.raises(ValueError, match="llm_samples"):
            config.set_setting(engine, "llm_samples", value)

    def test_sessions_record_the_effective_samples(self, engine):
        cfg = MagicMock(node_type="DirectoryClassification", extraction_method="llm", params='{"samples": 1}', enabled=True)
        config.set_setting(engine, "llm_samples", "3")
        with patch.object(config, "get_extraction_configs", return_value=[cfg]), patch.object(config, "get_derivation_configs", return_value=[]):
            assert config.llm_samples_per_step(engine)["DirectoryClassification"] == 3


def test_an_unset_setting_gives_each_step_its_own_again(engine):
    config.set_setting(engine, "llm_samples", "4")
    assert config.delete_setting(engine, "llm_samples") is True
    assert config.get_llm_samples(engine) is None
    assert config.delete_setting(engine, "llm_samples") is False
