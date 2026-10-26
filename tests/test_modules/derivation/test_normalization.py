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
        assert strip_archimate_suffix("Schema Service") == "Schema"

    def test_strips_interface(self):
        assert strip_archimate_suffix("Entity Metadata Interface") == "Entity Metadata"

    def test_strips_api(self):
        assert strip_archimate_suffix("Docs REST API") == "Docs REST"

    def test_strips_controller(self):
        assert strip_archimate_suffix("Store Controller") == "Store"

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
        assert strip_repo_prefix("Darkgreen Core", "darkgreen") == "Core"

    def test_case_insensitive(self):
        assert strip_repo_prefix("DARKGREEN Core", "darkgreen") == "Core"

    def test_matches_across_separators(self):
        assert strip_repo_prefix("EdgebasedXABCDeFg Engine", "Edgebased-X-ABC-DeFg") == "Engine"

    def test_non_matching_prefix_unchanged(self):
        assert strip_repo_prefix("Darkgreen Core", "otherproject") == "Darkgreen Core"

    def test_empty_repo_name_unchanged(self):
        assert strip_repo_prefix("Darkgreen Core", "") == "Darkgreen Core"

    def test_a_repo_name_spread_over_several_words(self):
        assert strip_repo_prefix("Tool Shed Registry", "ToolShed") == "Registry"
        assert strip_repo_prefix("Hillside Union Customer Core", "HillsideUnion") == "Customer Core"

    def test_a_name_that_is_only_the_repo_name_stays(self):
        assert strip_repo_prefix("Tool Shed", "ToolShed") == "Tool Shed"

    def test_part_of_a_word_is_no_prefix(self):
        assert strip_repo_prefix("Toolbox Shed Registry", "ToolShed") == "Toolbox Shed Registry"

    def test_single_token_not_stripped(self):
        assert strip_repo_prefix("Darkgreen", "darkgreen") == "Darkgreen"

    def test_prefix_only_at_start(self):
        assert strip_repo_prefix("Core Darkgreen Thing", "darkgreen") == "Core Darkgreen Thing"


class TestToTitleCase:
    def test_basic(self):
        assert to_title_case("store controller") == "Store Controller"

    def test_rest_and_Rest_converge(self):
        assert to_title_case("REST") == to_title_case("Rest") == "Rest"

    def test_empty(self):
        assert to_title_case("") == ""


class TestNormalizeForDedup:
    def test_strips_suffix(self):
        assert normalize_for_dedup("Store Controller", RepoContext()) == "Store"

    def test_strips_repo_prefix(self):
        ctx = RepoContext(repo_name="darkgreen")
        assert normalize_for_dedup("Darkgreen Core", ctx) == "Core"

    def test_repo_prefix_not_stripped_for_different_repo(self):
        ctx = RepoContext(repo_name="bigfarm")
        assert normalize_for_dedup("Darkgreen Core", ctx) == "Darkgreen Core"

    def test_rest_case_convergence(self):
        ctx = RepoContext()
        assert normalize_for_dedup("REST", ctx) == normalize_for_dedup("Rest", ctx)

    def test_interface_suffix_pair_converges(self):
        ctx = RepoContext()
        assert normalize_for_dedup("Entity Metadata Interface", ctx) == normalize_for_dedup("Entity Metadata", ctx)

    def test_empty(self):
        assert normalize_for_dedup("", RepoContext()) == ""

    def test_whitespace_collapsed(self):
        assert normalize_for_dedup("  Store   Controller  ", RepoContext()) == "Store"


class TestDesignInvariant:
    """Guard against repo-specific inputs creeping into the normalization module."""

    def test_no_hardcoded_repo_names(self):
        """The normalization module must not contain literal repo/product names."""
        path = Path(__file__).parent.parent.parent.parent / ("deriva/modules/derivation/refine/normalization.py")
        source = path.read_text(encoding="utf-8")
        # Product names never appear as literals
        found = [word for word in ("kafka", "spark", "mongodb") if word in source.lower()]
        assert not found, f"normalization.py must not contain product names; found: {found}"
        # Nor do the names the local scanner knows (where it is present)
        from deriva.services.overfit import scan_texts

        result = scan_texts({"source": source})
        if result["available"]:
            repo_terms = [f["finding"] for f in result["findings"] if "repo term" in f["finding"]]
            assert not repo_terms, f"normalization.py must not contain repository names; found: {repo_terms}"
