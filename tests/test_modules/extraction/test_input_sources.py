"""Tests for modules.extraction.input_sources module."""

from __future__ import annotations

import json

from deriva.modules.extraction.input_sources import (
    filter_files_by_input_sources,
    get_node_sources,
    has_file_sources,
    has_node_sources,
    matches_file_spec,
    parse_input_sources,
)


class TestParseInputSources:
    """Tests for parse_input_sources function."""

    def test_valid_json_with_files_and_nodes(self):
        """Should parse valid JSON with both files and nodes."""
        json_str = json.dumps(
            {
                "files": [{"type": "source", "subtype": "python"}],
                "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}],
            }
        )

        result = parse_input_sources(json_str)

        assert len(result["files"]) == 1
        assert result["files"][0]["type"] == "source"
        assert result["files"][0]["subtype"] == "python"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["label"] == "TypeDefinition"

    def test_valid_json_files_only(self):
        """Should parse JSON with only files specified."""
        json_str = json.dumps({"files": [{"type": "config", "subtype": "*"}]})

        result = parse_input_sources(json_str)

        assert len(result["files"]) == 1
        assert result["nodes"] == []

    def test_valid_json_nodes_only(self):
        """Should parse JSON with only nodes specified."""
        json_str = json.dumps({"nodes": [{"label": "File", "property": "path"}]})

        result = parse_input_sources(json_str)

        assert result["files"] == []
        assert len(result["nodes"]) == 1

    def test_empty_string(self):
        """Should return empty lists for empty string."""
        result = parse_input_sources("")

        assert result["files"] == []
        assert result["nodes"] == []

    def test_none_input(self):
        """Should return empty lists for None input."""
        result = parse_input_sources(None)

        assert result["files"] == []
        assert result["nodes"] == []

    def test_invalid_json(self):
        """Should return empty lists for invalid JSON."""
        result = parse_input_sources("{invalid json")

        assert result["files"] == []
        assert result["nodes"] == []

    def test_empty_json_object(self):
        """Should return empty lists for empty JSON object."""
        result = parse_input_sources("{}")

        assert result["files"] == []
        assert result["nodes"] == []

    def test_multiple_file_specs(self):
        """Should parse multiple file specifications."""
        json_str = json.dumps(
            {
                "files": [
                    {"type": "source", "subtype": "python"},
                    {"type": "source", "subtype": "javascript"},
                    {"type": "config", "subtype": "*"},
                ]
            }
        )

        result = parse_input_sources(json_str)

        assert len(result["files"]) == 3


class TestMatchesFileSpec:
    """Tests for matches_file_spec function."""

    def test_exact_type_and_subtype_match(self):
        """Should match when type and subtype match exactly."""
        specs = [{"type": "source", "subtype": "python"}]

        assert matches_file_spec("source", "python", specs) is True

    def test_wildcard_subtype_match(self):
        """Should match any subtype when spec uses wildcard."""
        specs = [{"type": "source", "subtype": "*"}]

        assert matches_file_spec("source", "python", specs) is True
        assert matches_file_spec("source", "javascript", specs) is True
        assert matches_file_spec("source", None, specs) is True

    def test_type_mismatch(self):
        """Should not match when type differs."""
        specs = [{"type": "source", "subtype": "python"}]

        assert matches_file_spec("config", "python", specs) is False

    def test_subtype_mismatch(self):
        """Should not match when subtype differs (without wildcard)."""
        specs = [{"type": "source", "subtype": "python"}]

        assert matches_file_spec("source", "javascript", specs) is False

    def test_empty_specs(self):
        """Should return False for empty specs list."""
        assert matches_file_spec("source", "python", []) is False

    def test_multiple_specs_any_match(self):
        """Should return True if any spec matches."""
        specs = [
            {"type": "source", "subtype": "python"},
            {"type": "source", "subtype": "javascript"},
            {"type": "config", "subtype": "*"},
        ]

        assert matches_file_spec("source", "python", specs) is True
        assert matches_file_spec("source", "javascript", specs) is True
        assert matches_file_spec("config", "yaml", specs) is True
        assert matches_file_spec("docs", "markdown", specs) is False

    def test_missing_subtype_in_spec_defaults_to_wildcard(self):
        """Should treat missing subtype in spec as wildcard."""
        specs = [{"type": "source"}]

        assert matches_file_spec("source", "python", specs) is True
        assert matches_file_spec("source", None, specs) is True

    def test_missing_type_in_spec(self):
        """Should not match when type is missing in spec."""
        specs = [{"subtype": "python"}]

        assert matches_file_spec("source", "python", specs) is False


class TestFilterFilesByInputSources:
    """Tests for filter_files_by_input_sources function."""

    def test_filter_by_single_type(self):
        """Should filter files by single type specification."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
            {"path": "config.yaml", "file_type": "config", "subtype": "yaml"},
            {"path": "utils.py", "file_type": "source", "subtype": "python"},
        ]
        input_sources = {"files": [{"type": "source", "subtype": "python"}]}

        result = filter_files_by_input_sources(files, input_sources)

        assert len(result) == 2
        assert all(f["file_type"] == "source" for f in result)

    def test_filter_by_wildcard_subtype(self):
        """Should filter files matching wildcard subtype."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
            {"path": "app.js", "file_type": "source", "subtype": "javascript"},
            {"path": "README.md", "file_type": "docs", "subtype": "markdown"},
        ]
        input_sources = {"files": [{"type": "source", "subtype": "*"}]}

        result = filter_files_by_input_sources(files, input_sources)

        assert len(result) == 2
        assert all(f["file_type"] == "source" for f in result)

    def test_filter_by_multiple_specs(self):
        """Should include files matching any spec."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
            {"path": "config.yaml", "file_type": "config", "subtype": "yaml"},
            {"path": "README.md", "file_type": "docs", "subtype": "markdown"},
        ]
        input_sources = {
            "files": [
                {"type": "source", "subtype": "python"},
                {"type": "config", "subtype": "*"},
            ]
        }

        result = filter_files_by_input_sources(files, input_sources)

        assert len(result) == 2
        paths = {f["path"] for f in result}
        assert "main.py" in paths
        assert "config.yaml" in paths

    def test_empty_file_specs(self):
        """Should return empty list when no file specs."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
        ]
        input_sources = {"files": []}

        result = filter_files_by_input_sources(files, input_sources)

        assert result == []

    def test_no_matching_files(self):
        """Should return empty list when no files match."""
        files = [
            {"path": "README.md", "file_type": "docs", "subtype": "markdown"},
        ]
        input_sources = {"files": [{"type": "source", "subtype": "python"}]}

        result = filter_files_by_input_sources(files, input_sources)

        assert result == []

    def test_missing_file_type_in_file(self):
        """Should handle files missing file_type gracefully."""
        files = [
            {"path": "main.py"},  # Missing file_type
            {"path": "utils.py", "file_type": "source", "subtype": "python"},
        ]
        input_sources = {"files": [{"type": "source", "subtype": "python"}]}

        result = filter_files_by_input_sources(files, input_sources)

        assert len(result) == 1
        assert result[0]["path"] == "utils.py"


class TestGetNodeSources:
    """Tests for get_node_sources function."""

    def test_returns_node_specs(self):
        """Should return node specifications."""
        input_sources = {
            "files": [{"type": "source", "subtype": "python"}],
            "nodes": [
                {"label": "TypeDefinition", "property": "codeSnippet"},
                {"label": "File", "property": "path"},
            ],
        }

        result = get_node_sources(input_sources)

        assert len(result) == 2
        assert result[0]["label"] == "TypeDefinition"
        assert result[1]["label"] == "File"

    def test_returns_empty_when_no_nodes(self):
        """Should return empty list when no nodes specified."""
        input_sources = {"files": [{"type": "source", "subtype": "python"}]}

        result = get_node_sources(input_sources)

        assert result == []

    def test_returns_empty_for_empty_input(self):
        """Should return empty list for empty input_sources."""
        result = get_node_sources({})

        assert result == []


class TestHasFileSources:
    """Tests for has_file_sources function."""

    def test_returns_true_when_files_present(self):
        """Should return True when files list is non-empty."""
        input_sources = {"files": [{"type": "source", "subtype": "python"}]}

        assert has_file_sources(input_sources) is True

    def test_returns_false_when_files_empty(self):
        """Should return False when files list is empty."""
        input_sources = {"files": []}

        assert has_file_sources(input_sources) is False

    def test_returns_false_when_files_missing(self):
        """Should return False when files key is missing."""
        input_sources = {"nodes": [{"label": "File"}]}

        assert has_file_sources(input_sources) is False

    def test_returns_false_for_empty_dict(self):
        """Should return False for empty dict."""
        assert has_file_sources({}) is False


class TestHasNodeSources:
    """Tests for has_node_sources function."""

    def test_returns_true_when_nodes_present(self):
        """Should return True when nodes list is non-empty."""
        input_sources = {"nodes": [{"label": "TypeDefinition"}]}

        assert has_node_sources(input_sources) is True

    def test_returns_false_when_nodes_empty(self):
        """Should return False when nodes list is empty."""
        input_sources = {"nodes": []}

        assert has_node_sources(input_sources) is False

    def test_returns_false_when_nodes_missing(self):
        """Should return False when nodes key is missing."""
        input_sources = {"files": [{"type": "source"}]}

        assert has_node_sources(input_sources) is False

    def test_returns_false_for_empty_dict(self):
        """Should return False for empty dict."""
        assert has_node_sources({}) is False
