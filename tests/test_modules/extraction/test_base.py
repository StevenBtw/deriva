"""Tests for modules.extraction.extraction_base module."""

from deriva.common.types import LLMDetails
from deriva.modules.extraction.base import (
    create_empty_llm_details,
    create_extraction_result,
    current_timestamp,
    deduplicate_nodes,
    filter_files_by_input_sources,
    generate_edge_id,
    generate_node_id,
    get_node_sources,
    has_file_sources,
    has_node_sources,
    is_python_file,
    matches_file_spec,
    normalize_concept_name,
    normalize_package_name,
    normalize_technology_name,
    parse_input_sources,
    parse_json_response,
    singularize,
    strip_chunk_suffix,
    validate_required_fields,
)


class TestGenerateNodeId:
    """Tests for generate_node_id function."""

    def test_basic_node_id(self):
        """Should generate formatted node ID."""
        node_id = generate_node_id("concept", "myrepo", "UserAuth")
        assert node_id == "concept_myrepo_userauth"

    def test_normalizes_spaces(self):
        """Should replace spaces with underscores."""
        node_id = generate_node_id("type", "repo", "User Auth Service")
        assert node_id == "type_repo_user_auth_service"

    def test_normalizes_hyphens(self):
        """Should replace hyphens with underscores."""
        node_id = generate_node_id("method", "repo", "get-user-data")
        assert node_id == "method_repo_get_user_data"

    def test_removes_special_chars(self):
        """Should remove non-alphanumeric characters."""
        node_id = generate_node_id("concept", "repo", "User@Auth#123")
        assert node_id == "concept_repo_userauth123"


class TestGenerateEdgeId:
    """Tests for generate_edge_id function."""

    def test_basic_edge_id(self):
        """Should generate formatted edge ID."""
        edge_id = generate_edge_id("node_a", "node_b", "DEPENDS_ON")
        assert edge_id == "depends_on_node_a_to_node_b"


class TestCurrentTimestamp:
    """Tests for current_timestamp function."""

    def test_returns_iso_format(self):
        """Should return ISO format timestamp with Z suffix."""
        ts = current_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts


class TestParseJsonResponse:
    """Tests for parse_json_response function."""

    def test_valid_json_with_array(self):
        """Should parse valid JSON with expected array key."""
        response = '{"concepts": [{"name": "Auth"}, {"name": "User"}]}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["errors"] == []

    def test_missing_array_key(self):
        """Should fail when array key is missing."""
        response = '{"items": []}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert 'missing "concepts"' in result["errors"][0]

    def test_non_array_value(self):
        """Should fail when value is not an array."""
        response = '{"concepts": "not an array"}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert "must be an array" in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "{invalid json"
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_all_fields_present(self):
        """Should return empty errors when all fields present."""
        data = {"name": "Test", "id": "123"}
        errors = validate_required_fields(data, ["name", "id"])
        assert errors == []

    def test_missing_field(self):
        """Should return error for missing field."""
        data = {"name": "Test"}
        errors = validate_required_fields(data, ["name", "id"])
        assert len(errors) == 1
        assert "id" in errors[0]

    def test_empty_field(self):
        """Should return error for empty field."""
        data = {"name": "", "id": "123"}
        errors = validate_required_fields(data, ["name", "id"])
        assert len(errors) == 1
        assert "name" in errors[0]


class TestCreateExtractionResult:
    """Tests for create_extraction_result function."""

    def test_success_result(self):
        """Should create success result structure."""
        result = create_extraction_result(success=True, nodes=[{"id": "node1"}], edges=[{"from": "a", "to": "b"}], errors=[], stats={"count": 1})

        assert result["success"] is True
        assert len(result["elements"]) == 1
        assert len(result["relationships"]) == 1
        assert result["errors"] == []
        assert result["stage"] == "extraction"
        assert "timestamp" in result
        assert "duration_ms" in result
        assert "llm_details" not in result

    def test_result_with_llm_details(self):
        """Should include LLM details when provided."""
        llm_details: LLMDetails = {"tokens_in": 100, "tokens_out": 50}
        result = create_extraction_result(success=True, nodes=[], edges=[], errors=[], stats={}, llm_details=llm_details)

        assert result["llm_details"] == llm_details


class TestCreateEmptyLlmDetails:
    """Tests for create_empty_llm_details function."""

    def test_returns_expected_structure(self):
        """Should return dict with all expected keys."""
        details = create_empty_llm_details()

        assert details["prompt"] == ""
        assert details["response"] == ""
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0
        assert details["cache_used"] is False


class TestStripChunkSuffix:
    """Tests for strip_chunk_suffix function."""

    def test_strips_lines_suffix(self):
        """Should strip (lines X-Y) suffix."""
        result = strip_chunk_suffix("src/app.py (lines 1-100)")
        assert result == "src/app.py"

    def test_no_suffix_unchanged(self):
        """Should return unchanged path without suffix."""
        result = strip_chunk_suffix("src/app.py")
        assert result == "src/app.py"

    def test_strips_with_different_line_numbers(self):
        """Should handle different line number formats."""
        result = strip_chunk_suffix("module/utils.py (lines 500-999)")
        assert result == "module/utils.py"


class TestDeduplicateNodes:
    """Tests for deduplicate_nodes function."""

    def test_removes_duplicates(self):
        """Should remove duplicate nodes by key."""
        nodes = [
            {"node_id": "a", "name": "First"},
            {"node_id": "b", "name": "Second"},
            {"node_id": "a", "name": "First Duplicate"},
        ]
        result = deduplicate_nodes(nodes)
        assert len(result) == 2
        assert result[0]["name"] == "First"
        assert result[1]["name"] == "Second"

    def test_preserves_order(self):
        """Should preserve first occurrence order."""
        nodes = [
            {"node_id": "c", "name": "C"},
            {"node_id": "a", "name": "A"},
            {"node_id": "b", "name": "B"},
            {"node_id": "a", "name": "A Dup"},
        ]
        result = deduplicate_nodes(nodes)
        assert [n["node_id"] for n in result] == ["c", "a", "b"]

    def test_empty_list(self):
        """Should handle empty list."""
        result = deduplicate_nodes([])
        assert result == []

    def test_custom_key(self):
        """Should allow custom key field."""
        nodes = [
            {"id": "x", "value": 1},
            {"id": "y", "value": 2},
            {"id": "x", "value": 3},
        ]
        result = deduplicate_nodes(nodes, key="id")
        assert len(result) == 2


class TestParseInputSources:
    """Tests for parse_input_sources function."""

    def test_valid_json(self):
        """Should parse valid JSON input sources."""
        json_str = '{"files": [{"type": "source"}], "nodes": ["node1"]}'
        result = parse_input_sources(json_str)
        assert len(result["files"]) == 1
        assert len(result["nodes"]) == 1

    def test_empty_string(self):
        """Should return empty lists for empty string."""
        result = parse_input_sources("")
        assert result == {"files": [], "nodes": []}

    def test_none_input(self):
        """Should return empty lists for None."""
        result = parse_input_sources(None)
        assert result == {"files": [], "nodes": []}

    def test_invalid_json(self):
        """Should return empty lists for invalid JSON."""
        result = parse_input_sources("{invalid json")
        assert result == {"files": [], "nodes": []}

    def test_missing_keys(self):
        """Should handle missing keys."""
        result = parse_input_sources('{"other": "value"}')
        assert result == {"files": [], "nodes": []}


class TestMatchesFileSpec:
    """Tests for matches_file_spec function."""

    def test_matches_type_only(self):
        """Should match when only type specified."""
        specs = [{"type": "source"}]
        assert matches_file_spec("source", "python", specs) is True
        assert matches_file_spec("docs", "markdown", specs) is False

    def test_matches_type_and_subtype(self):
        """Should match when both type and subtype specified."""
        specs = [{"type": "source", "subtype": "python"}]
        assert matches_file_spec("source", "python", specs) is True
        assert matches_file_spec("source", "javascript", specs) is False

    def test_matches_any_spec(self):
        """Should match if any spec matches."""
        specs = [
            {"type": "source", "subtype": "python"},
            {"type": "docs"},
        ]
        assert matches_file_spec("docs", "markdown", specs) is True
        assert matches_file_spec("source", "python", specs) is True

    def test_empty_specs(self):
        """Should not match when no specs provided."""
        assert matches_file_spec("source", "python", []) is False


class TestIsPythonFile:
    """Tests for is_python_file function."""

    def test_python_subtype(self):
        """Should identify python subtype."""
        assert is_python_file("python") is True
        assert is_python_file("Python") is True
        assert is_python_file("PYTHON") is True

    def test_non_python_subtype(self):
        """Should reject non-Python subtypes."""
        assert is_python_file("javascript") is False
        assert is_python_file("java") is False
        assert is_python_file("typescript") is False

    def test_none_subtype(self):
        """Should reject None subtype."""
        assert is_python_file(None) is False

    def test_empty_subtype(self):
        """Should reject empty string subtype."""
        assert is_python_file("") is False


class TestNormalizePackageName:
    """Tests for normalize_package_name function."""

    def test_canonical_name(self):
        """Should return canonical name for known packages."""
        assert normalize_package_name("requests") == "Requests"
        assert normalize_package_name("flask") == "Flask"
        assert normalize_package_name("numpy") == "NumPy"

    def test_unknown_package_preserves_case(self):
        """Should preserve case for unknown packages."""
        result = normalize_package_name("my_custom_tool")
        assert result == "my_custom_tool"

    def test_strips_redundant_suffixes(self):
        """Should strip redundant suffixes like _lib."""
        result = normalize_package_name("my_custom_lib")
        assert result == "my_custom"

    def test_empty_name(self):
        """Should return empty for empty input."""
        assert normalize_package_name("") == ""

    def test_canonical_case_insensitive(self):
        """Should match canonical names case-insensitively."""
        assert normalize_package_name("REQUESTS") == "Requests"
        assert normalize_package_name("Flask") == "Flask"


class TestNormalizeConceptName:
    """Tests for normalize_concept_name function."""

    def test_singularizes_plural(self):
        """Should singularize plural concept names."""
        result = normalize_concept_name("Users")
        assert result == "User"

    def test_converts_to_camelcase(self):
        """Should convert underscored names to CamelCase."""
        result = normalize_concept_name("user_authentication")
        assert result == "UserAuthentication"

    def test_handles_spaces(self):
        """Should convert spaced names to CamelCase."""
        result = normalize_concept_name("user authentication")
        assert result == "UserAuthentication"

    def test_empty_name(self):
        """Should return empty for empty input."""
        assert normalize_concept_name("") == ""


class TestNormalizeTechnologyName:
    """Tests for normalize_technology_name function."""

    def test_canonical_technology(self):
        """Should return canonical name for known technologies."""
        result = normalize_technology_name("flask")
        assert result == "Flask"

    def test_unknown_technology(self):
        """Should preserve case for unknown technologies."""
        result = normalize_technology_name("MyFramework")
        assert result == "MyFramework"

    def test_empty_name(self):
        """Should return empty for empty input."""
        assert normalize_technology_name("") == ""


class TestSingularize:
    """Tests for singularize function."""

    def test_regular_plural(self):
        """Should singularize regular plurals."""
        assert singularize("users") == "user"
        assert singularize("files") == "file"

    def test_es_plural(self):
        """Should singularize -es plurals."""
        assert singularize("classes") == "class"
        assert singularize("boxes") == "box"

    def test_ies_plural(self):
        """Should singularize -ies plurals."""
        assert singularize("entities") == "entity"
        assert singularize("queries") == "query"

    def test_already_singular(self):
        """Should not change already singular words."""
        assert singularize("user") == "user"
        assert singularize("class") == "class"


class TestFilterFilesByInputSources:
    """Tests for filter_files_by_input_sources function."""

    def test_filters_by_type(self):
        """Should filter files matching type spec."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
            {"path": "README.md", "file_type": "docs", "subtype": "markdown"},
        ]
        input_sources = {"files": [{"type": "source"}], "nodes": []}
        result = filter_files_by_input_sources(files, input_sources)
        assert len(result) == 1
        assert result[0]["path"] == "main.py"

    def test_returns_empty_when_no_file_sources(self):
        """Should return empty list when no file sources specified."""
        files = [
            {"path": "main.py", "file_type": "source"},
            {"path": "README.md", "file_type": "docs"},
        ]
        input_sources = {"files": [], "nodes": []}
        result = filter_files_by_input_sources(files, input_sources)
        assert result == []

    def test_filters_by_type_and_subtype(self):
        """Should filter files matching type and subtype."""
        files = [
            {"path": "main.py", "file_type": "source", "subtype": "python"},
            {"path": "app.js", "file_type": "source", "subtype": "javascript"},
        ]
        input_sources = {"files": [{"type": "source", "subtype": "python"}], "nodes": []}
        result = filter_files_by_input_sources(files, input_sources)
        assert len(result) == 1
        assert result[0]["path"] == "main.py"


class TestGetNodeSources:
    """Tests for get_node_sources function."""

    def test_returns_nodes_list(self):
        """Should return nodes list from input sources."""
        input_sources = {"files": [], "nodes": [{"id": "node1"}, {"id": "node2"}]}
        result = get_node_sources(input_sources)
        assert len(result) == 2
        assert result[0]["id"] == "node1"

    def test_returns_empty_when_no_nodes(self):
        """Should return empty list when no nodes."""
        input_sources = {"files": [], "nodes": []}
        result = get_node_sources(input_sources)
        assert result == []


class TestHasFileSources:
    """Tests for has_file_sources function."""

    def test_true_when_files_present(self):
        """Should return True when files are present."""
        input_sources = {"files": [{"type": "source"}], "nodes": []}
        assert has_file_sources(input_sources) is True

    def test_false_when_no_files(self):
        """Should return False when no files."""
        input_sources = {"files": [], "nodes": []}
        assert has_file_sources(input_sources) is False


class TestHasNodeSources:
    """Tests for has_node_sources function."""

    def test_true_when_nodes_present(self):
        """Should return True when nodes are present."""
        input_sources = {"files": [], "nodes": [{"id": "node1"}]}
        assert has_node_sources(input_sources) is True

    def test_false_when_no_nodes(self):
        """Should return False when no nodes."""
        input_sources = {"files": [], "nodes": []}
        assert has_node_sources(input_sources) is False
