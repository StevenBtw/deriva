"""Tests for refine.normalization dedup helpers."""

from __future__ import annotations

from pathlib import Path

from deriva.modules.derivation.refine.normalization import (
    RepoContext,
    normalize_for_dedup,
    strip_archimate_suffix,
    strip_repo_prefix,
    to_title_case,
)


class TestStripArchimateSuffix:
    def test_strips_component(self):
        assert strip_archimate_suffix("Mongo Component") == "Mongo"

    def test_strips_service(self):
        assert strip_archimate_suffix("Metadata Service") == "Metadata"

    def test_strips_interface(self):
        assert strip_archimate_suffix("Entity Metadata Interface") == "Entity Metadata"

    def test_strips_api(self):
        assert strip_archimate_suffix("Data REST API") == "Data REST"

    def test_strips_controller(self):
        assert strip_archimate_suffix("Mongo Controller") == "Mongo"

    def test_case_insensitive(self):
        assert strip_archimate_suffix("Mongo COMPONENT") == "Mongo"

    def test_no_suffix_unchanged(self):
        assert strip_archimate_suffix("User") == "User"
        assert strip_archimate_suffix("Core") == "Core"

    def test_single_token_not_stripped(self):
        assert strip_archimate_suffix("Service") == "Service"

    def test_empty(self):
        assert strip_archimate_suffix("") == ""


class TestStripRepoPrefix:
    def test_strips_matching_prefix(self):
        assert strip_repo_prefix("Lightblue Core", "lightblue") == "Core"

    def test_case_insensitive(self):
        assert strip_repo_prefix("LIGHTBLUE Core", "lightblue") == "Core"

    def test_matches_across_separators(self):
        assert strip_repo_prefix("CloudbasedSBPMWfMS Engine", "Cloudbased-S-BPM-WfMS") == "Engine"

    def test_non_matching_prefix_unchanged(self):
        assert strip_repo_prefix("Lightblue Core", "otherproject") == "Lightblue Core"

    def test_empty_repo_name_unchanged(self):
        assert strip_repo_prefix("Lightblue Core", "") == "Lightblue Core"

    def test_a_repo_name_spread_over_several_words(self):
        assert strip_repo_prefix("Tea Store Registry", "TeaStore") == "Registry"
        assert strip_repo_prefix("Lakeside Mutual Customer Core", "LakesideMutual") == "Customer Core"

    def test_a_name_that_is_only_the_repo_name_stays(self):
        assert strip_repo_prefix("Tea Store", "TeaStore") == "Tea Store"

    def test_part_of_a_word_is_no_prefix(self):
        assert strip_repo_prefix("Teapot Store Registry", "TeaStore") == "Teapot Store Registry"

    def test_single_token_not_stripped(self):
        assert strip_repo_prefix("Lightblue", "lightblue") == "Lightblue"

    def test_prefix_only_at_start(self):
        assert strip_repo_prefix("Core Lightblue Thing", "lightblue") == "Core Lightblue Thing"


class TestToTitleCase:
    def test_basic(self):
        assert to_title_case("mongo controller") == "Mongo Controller"

    def test_rest_and_Rest_converge(self):
        assert to_title_case("REST") == to_title_case("Rest") == "Rest"

    def test_empty(self):
        assert to_title_case("") == ""


class TestNormalizeForDedup:
    def test_strips_suffix(self):
        assert normalize_for_dedup("Mongo Controller", RepoContext()) == "Mongo"

    def test_strips_repo_prefix(self):
        ctx = RepoContext(repo_name="lightblue")
        assert normalize_for_dedup("Lightblue Core", ctx) == "Core"

    def test_repo_prefix_not_stripped_for_different_repo(self):
        ctx = RepoContext(repo_name="bigdata")
        assert normalize_for_dedup("Lightblue Core", ctx) == "Lightblue Core"

    def test_rest_case_convergence(self):
        ctx = RepoContext()
        assert normalize_for_dedup("REST", ctx) == normalize_for_dedup("Rest", ctx)

    def test_interface_suffix_pair_converges(self):
        ctx = RepoContext()
        assert normalize_for_dedup("Entity Metadata Interface", ctx) == normalize_for_dedup("Entity Metadata", ctx)

    def test_empty(self):
        assert normalize_for_dedup("", RepoContext()) == ""

    def test_whitespace_collapsed(self):
        assert normalize_for_dedup("  Mongo   Controller  ", RepoContext()) == "Mongo"


class TestDesignInvariant:
    """Guard against repo-specific inputs creeping into the normalization module."""

    def test_no_hardcoded_repo_names(self):
        """The normalization module must not contain literal repo/product names."""
        path = Path(__file__).parent.parent.parent.parent / ("deriva/modules/derivation/refine/normalization.py")
        source = path.read_text(encoding="utf-8")
        # These are the benchmark repo names — they must never appear as literals.
        forbidden = ["lightblue", "bigdata", "cloudbased", "kafka", "spark", "mongodb"]
        found = [word for word in forbidden if word.lower() in source.lower()]
        # Allow in comments/docstrings only if the whole line is a comment.
        # Simplest guard: no appearance at all.
        assert not found, f"normalization.py must not contain repo/product names; found: {found}"
