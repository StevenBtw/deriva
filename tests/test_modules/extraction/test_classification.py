"""Tests for modules.extraction.classification module."""

from __future__ import annotations

from deriva.modules.extraction.classification import (
    _match_path_pattern,
    build_registry_update_list,
    classify_files,
    get_undefined_extensions,
)


class TestMatchPathPattern:
    """Tests for _match_path_pattern helper function."""

    def test_matches_tests_directory(self):
        """Should match files in tests directory."""
        assert _match_path_pattern("tests/test_main.py", "**/tests/**") is True
        assert _match_path_pattern("src/tests/unit/test_util.py", "**/tests/**") is True

    def test_matches_with_backslashes(self):
        """Should handle Windows-style paths."""
        assert _match_path_pattern("tests\\test_main.py", "**/tests/**") is True

    def test_matches_simple_glob(self):
        """Should match simple glob patterns without **."""
        assert _match_path_pattern("docs/readme.md", "docs/*") is True

    def test_case_insensitive(self):
        """Should match case-insensitively."""
        assert _match_path_pattern("Tests/test_main.py", "**/tests/**") is True
        assert _match_path_pattern("TESTS/Test_Main.py", "**/tests/**") is True

    def test_no_match_returns_false(self):
        """Should return False for non-matching paths."""
        assert _match_path_pattern("src/main.py", "**/tests/**") is False


class TestClassifyFiles:
    """Tests for classify_files function."""

    def test_classify_by_extension(self):
        """Should classify files by extension."""
        files = ["main.py", "app.js", "style.css"]
        registry = [
            {"extension": ".py", "file_type": "source", "subtype": "python"},
            {"extension": ".js", "file_type": "source", "subtype": "javascript"},
        ]

        result = classify_files(files, registry)

        assert result["stats"]["classified_count"] == 2
        assert result["stats"]["undefined_count"] == 1  # .css not in registry

    def test_classify_by_filename(self):
        """Should classify by full filename match."""
        files = ["requirements.txt", "Makefile", "main.py"]
        registry = [
            {"extension": "requirements.txt", "file_type": "dependency", "subtype": "python"},
            {"extension": "makefile", "file_type": "build", "subtype": "make"},
            {"extension": ".py", "file_type": "source", "subtype": "python"},
        ]

        result = classify_files(files, registry)

        assert result["stats"]["classified_count"] == 3
        # Check that requirements.txt is classified as dependency
        req_file = next(f for f in result["classified"] if "requirements.txt" in f["path"])
        assert req_file["file_type"] == "dependency"

    def test_classify_by_wildcard_pattern(self):
        """Should classify by wildcard pattern."""
        files = ["test_main.py", "main.py", "utils.py"]
        registry = [
            {"extension": "test_*.py", "file_type": "test", "subtype": "pytest"},
            {"extension": ".py", "file_type": "source", "subtype": "python"},
        ]

        result = classify_files(files, registry)

        # test_main.py should be classified as test, others as source
        test_file = next(f for f in result["classified"] if f["path"] == "test_main.py")
        assert test_file["file_type"] == "test"

        main_file = next(f for f in result["classified"] if f["path"] == "main.py")
        assert main_file["file_type"] == "source"

    def test_classify_by_path_pattern(self):
        """Should classify by path pattern."""
        files = ["src/main.py", "tests/test_main.py"]
        registry = [
            {"extension": "path:**/tests/**", "file_type": "test", "subtype": ""},
            {"extension": ".py", "file_type": "source", "subtype": "python"},
        ]

        result = classify_files(files, registry)

        # tests/test_main.py should match path pattern first
        test_file = next(f for f in result["classified"] if "tests/test_main.py" in f["path"])
        assert test_file["file_type"] == "test"

        src_file = next(f for f in result["classified"] if "src/main.py" in f["path"])
        assert src_file["file_type"] == "source"

    def test_returns_undefined_for_unknown_extensions(self):
        """Should return undefined for unknown file types."""
        files = ["app.xyz", "data.unknown"]
        registry = [{"extension": ".py", "file_type": "source", "subtype": "python"}]

        result = classify_files(files, registry)

        assert result["stats"]["undefined_count"] == 2
        assert len(result["undefined"]) == 2

    def test_handles_no_extension(self):
        """Should handle files without extension."""
        files = ["Dockerfile", "Makefile"]
        registry = [
            {"extension": "dockerfile", "file_type": "config", "subtype": "docker"},
        ]

        result = classify_files(files, registry)

        # Dockerfile should match
        assert result["stats"]["classified_count"] == 1
        # Makefile with no extension and not in registry
        assert result["stats"]["undefined_count"] == 1

    def test_returns_stats(self):
        """Should return statistics."""
        files = ["a.py", "b.py", "c.txt"]
        registry = [{"extension": ".py", "file_type": "source", "subtype": "python"}]

        result = classify_files(files, registry)

        assert result["stats"]["total_files"] == 3
        assert result["stats"]["classified_count"] == 2
        assert result["stats"]["undefined_count"] == 1
        assert result["stats"]["error_count"] == 0

    def test_empty_input(self):
        """Should handle empty input."""
        result = classify_files([], [])

        assert result["stats"]["total_files"] == 0
        assert result["classified"] == []
        assert result["undefined"] == []

    def test_dotfiles(self):
        """Should classify dotfiles by full filename match."""
        files = [".gitignore", ".env"]
        registry = [
            {"extension": ".gitignore", "file_type": "vcs", "subtype": "git"},
        ]

        result = classify_files(files, registry)

        # Only .gitignore matches (by filename), .env has no extension
        assert result["stats"]["classified_count"] == 1
        assert result["stats"]["undefined_count"] == 1


class TestGetUndefinedExtensions:
    """Tests for get_undefined_extensions function."""

    def test_extracts_unique_extensions(self):
        """Should extract unique extensions from undefined files."""
        undefined = [
            {"path": "a.xyz", "extension": ".xyz"},
            {"path": "b.xyz", "extension": ".xyz"},
            {"path": "c.abc", "extension": ".abc"},
        ]

        result = get_undefined_extensions(undefined)

        assert len(result) == 2
        assert ".abc" in result
        assert ".xyz" in result

    def test_returns_sorted_list(self):
        """Should return sorted list."""
        undefined = [
            {"path": "c.zzz", "extension": ".zzz"},
            {"path": "a.aaa", "extension": ".aaa"},
        ]

        result = get_undefined_extensions(undefined)

        assert result == [".aaa", ".zzz"]

    def test_empty_input(self):
        """Should handle empty input."""
        result = get_undefined_extensions([])
        assert result == []

    def test_skips_empty_extensions(self):
        """Should skip entries without extensions."""
        undefined = [
            {"path": "file", "extension": ""},
            {"path": "a.py", "extension": ".py"},
        ]

        result = get_undefined_extensions(undefined)

        assert result == [".py"]


class TestBuildRegistryUpdateList:
    """Tests for build_registry_update_list function."""

    def test_creates_registry_entries(self):
        """Should create registry entry dicts."""
        extensions = [".xyz", ".abc"]

        result = build_registry_update_list(extensions)

        assert len(result) == 2
        assert {"extension": ".xyz", "file_type": "Undefined"} in result
        assert {"extension": ".abc", "file_type": "Undefined"} in result

    def test_custom_default_type(self):
        """Should use custom default type."""
        extensions = [".xyz"]

        result = build_registry_update_list(extensions, default_type="unknown")

        assert result[0]["file_type"] == "unknown"

    def test_empty_input(self):
        """Should handle empty input."""
        result = build_registry_update_list([])
        assert result == []
