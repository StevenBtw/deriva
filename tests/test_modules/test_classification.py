"""Tests for modules.classification module."""

import pytest

from deriva.modules.extraction.classification import (
    build_registry_update_list,
    classify_files,
    get_undefined_extensions,
)


class TestClassifyFiles:
    """Tests for classify_files function."""

    @pytest.fixture
    def sample_registry(self):
        """Sample file type registry."""
        return [
            {"extension": ".py", "file_type": "source", "subtype": "python"},
            {"extension": ".js", "file_type": "source", "subtype": "javascript"},
            {"extension": ".md", "file_type": "documentation", "subtype": "markdown"},
            {"extension": "requirements.txt", "file_type": "dependency", "subtype": "python"},
            {"extension": "test_*.py", "file_type": "test", "subtype": "python"},
            {"extension": "Makefile", "file_type": "build", "subtype": "make"},
        ]

    def test_classifies_by_extension(self, sample_registry):
        """Should classify files by extension."""
        result = classify_files(file_paths=["src/main.py", "src/utils.js"], file_type_registry=sample_registry)

        assert result["stats"]["classified_count"] == 2
        assert result["stats"]["undefined_count"] == 0
        assert result["classified"][0]["file_type"] == "source"
        assert result["classified"][0]["subtype"] == "python"

    def test_classifies_by_full_filename(self, sample_registry):
        """Should classify files by full filename match."""
        result = classify_files(file_paths=["requirements.txt", "Makefile"], file_type_registry=sample_registry)

        assert result["stats"]["classified_count"] == 2
        classified_types = [c["file_type"] for c in result["classified"]]
        assert "dependency" in classified_types
        assert "build" in classified_types

    def test_classifies_by_wildcard_pattern(self, sample_registry):
        """Should classify files by wildcard pattern."""
        result = classify_files(file_paths=["test_main.py", "test_utils.py"], file_type_registry=sample_registry)

        assert result["stats"]["classified_count"] == 2
        assert all(c["file_type"] == "test" for c in result["classified"])

    def test_undefined_for_unknown_extension(self, sample_registry):
        """Should mark unknown extensions as undefined."""
        result = classify_files(file_paths=["src/style.css", "data/config.yaml"], file_type_registry=sample_registry)

        assert result["stats"]["undefined_count"] == 2
        assert result["undefined"][0]["reason"] == "unknown_extension"

    def test_undefined_for_no_extension(self, sample_registry):
        """Should mark files without extension as undefined."""
        result = classify_files(file_paths=["src/LICENSE", "docs/README"], file_type_registry=sample_registry)

        # These should be undefined since they don't match filename patterns
        # and have no extension
        assert result["stats"]["undefined_count"] == 2

    def test_priority_filename_over_extension(self, sample_registry):
        """Full filename should have priority over extension."""
        # requirements.txt should match filename, not .txt extension
        result = classify_files(file_paths=["requirements.txt"], file_type_registry=sample_registry)

        assert result["classified"][0]["file_type"] == "dependency"

    def test_priority_wildcard_over_extension(self, sample_registry):
        """Wildcard pattern should have priority over extension."""
        # test_main.py should match test_*.py, not .py
        result = classify_files(file_paths=["test_main.py"], file_type_registry=sample_registry)

        assert result["classified"][0]["file_type"] == "test"

    def test_handles_empty_file_list(self, sample_registry):
        """Should handle empty file list."""
        result = classify_files([], sample_registry)

        assert result["stats"]["total_files"] == 0
        assert result["classified"] == []
        assert result["undefined"] == []

    def test_handles_empty_registry(self):
        """Should mark all files as undefined with empty registry."""
        result = classify_files(file_paths=["main.py", "index.js"], file_type_registry=[])

        assert result["stats"]["undefined_count"] == 2

    def test_skips_malformed_registry_entries(self):
        """Should skip registry entries missing extension or file_type."""
        registry = [
            {"extension": ".py", "file_type": "source"},  # Valid
            {"extension": ".js"},  # Missing file_type
            {"file_type": "config"},  # Missing extension
            {},  # Missing both
        ]
        result = classify_files(file_paths=["main.py", "index.js"], file_type_registry=registry)

        # Only .py should be classified
        assert result["stats"]["classified_count"] == 1
        assert result["stats"]["undefined_count"] == 1
        assert result["classified"][0]["subtype"] == ""  # No subtype for .py entry


class TestGetUndefinedExtensions:
    """Tests for get_undefined_extensions function."""

    def test_extracts_unique_extensions(self):
        """Should extract unique extensions."""
        undefined = [
            {"path": "a.css", "extension": ".css"},
            {"path": "b.css", "extension": ".css"},
            {"path": "c.yaml", "extension": ".yaml"},
        ]

        extensions = get_undefined_extensions(undefined)

        assert len(extensions) == 2
        assert ".css" in extensions
        assert ".yaml" in extensions

    def test_returns_sorted_list(self):
        """Should return sorted list."""
        undefined = [
            {"path": "a.yaml", "extension": ".yaml"},
            {"path": "b.css", "extension": ".css"},
        ]

        extensions = get_undefined_extensions(undefined)

        assert extensions == [".css", ".yaml"]

    def test_handles_empty_list(self):
        """Should handle empty list."""
        extensions = get_undefined_extensions([])
        assert extensions == []

    def test_skips_empty_extensions(self):
        """Should skip entries with empty extension."""
        undefined = [
            {"path": "a.css", "extension": ".css"},
            {"path": "LICENSE", "extension": ""},
        ]

        extensions = get_undefined_extensions(undefined)

        assert extensions == [".css"]


class TestBuildRegistryUpdateList:
    """Tests for build_registry_update_list function."""

    def test_creates_registry_entries(self):
        """Should create registry entries with default type."""
        extensions = [".css", ".yaml"]

        entries = build_registry_update_list(extensions)

        assert len(entries) == 2
        assert entries[0] == {"extension": ".css", "file_type": "Undefined"}
        assert entries[1] == {"extension": ".yaml", "file_type": "Undefined"}

    def test_custom_default_type(self):
        """Should use custom default type."""
        extensions = [".css"]

        entries = build_registry_update_list(extensions, default_type="unknown")

        assert entries[0]["file_type"] == "unknown"

    def test_empty_extensions(self):
        """Should handle empty list."""
        entries = build_registry_update_list([])
        assert entries == []
