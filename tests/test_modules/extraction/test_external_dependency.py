"""Tests for modules.extraction.external_dependency module."""

from __future__ import annotations

from typing import Any, cast

from deriva.modules.extraction.external_dependency import (
    EXTERNAL_DEPENDENCY_SCHEMA,
    PYTHON_STDLIB_MODULES,
    _build_dependency_node_and_edge,
    _build_result,
    _extract_from_package_json,
    _extract_from_pyproject_toml,
    _extract_from_requirements_txt,
    build_external_dependency_node,
    build_extraction_prompt,
    extract_external_dependencies,
    extract_external_dependencies_batch,
    get_extraction_method,
    parse_llm_response,
    parse_requirement_line,
)

PROMPT_TEXTS = {"persona": "Analyze the source.", "task": "Extract the items."}

# =============================================================================
# Schema Tests
# =============================================================================


class TestExternalDependencySchema:
    """Tests for the JSON schema definition."""

    def test_schema_has_required_structure(self):
        """Schema should have the expected structure."""
        assert EXTERNAL_DEPENDENCY_SCHEMA["name"] == "external_dependency_extraction"
        assert EXTERNAL_DEPENDENCY_SCHEMA["strict"] is True
        schema = cast(dict[str, Any], EXTERNAL_DEPENDENCY_SCHEMA["schema"])
        assert "dependencies" in schema["properties"]

    def test_schema_dependency_fields(self):
        """Schema should define all dependency fields."""
        schema = cast(dict[str, Any], EXTERNAL_DEPENDENCY_SCHEMA["schema"])
        items = schema["properties"]["dependencies"]["items"]
        required_fields = items["required"]

        assert "dependencyName" in required_fields
        assert "dependencyCategory" in required_fields
        assert "version" in required_fields
        assert "ecosystem" in required_fields
        assert "description" in required_fields
        assert "confidence" in required_fields

    def test_dependency_category_enum_values(self):
        """Schema should have correct enum values for dependencyCategory."""
        schema = cast(dict[str, Any], EXTERNAL_DEPENDENCY_SCHEMA["schema"])
        items = schema["properties"]["dependencies"]["items"]
        enum_values = items["properties"]["dependencyCategory"]["enum"]

        assert "library" in enum_values
        assert "external_api" in enum_values
        assert "external_service" in enum_values
        assert "external_database" in enum_values


# =============================================================================
# PYTHON_STDLIB_MODULES Tests
# =============================================================================


class TestPythonStdlibModules:
    """Tests for PYTHON_STDLIB_MODULES constant."""

    def test_contains_common_modules(self):
        """Should contain common standard library modules."""
        assert "os" in PYTHON_STDLIB_MODULES
        assert "sys" in PYTHON_STDLIB_MODULES
        assert "json" in PYTHON_STDLIB_MODULES
        assert "re" in PYTHON_STDLIB_MODULES
        assert "pathlib" in PYTHON_STDLIB_MODULES
        assert "typing" in PYTHON_STDLIB_MODULES

    def test_does_not_contain_external_packages(self):
        """Should not contain external packages."""
        assert "flask" not in PYTHON_STDLIB_MODULES
        assert "django" not in PYTHON_STDLIB_MODULES
        assert "numpy" not in PYTHON_STDLIB_MODULES
        assert "pandas" not in PYTHON_STDLIB_MODULES


# =============================================================================
# get_extraction_method Tests
# =============================================================================


class TestGetExtractionMethod:
    """Tests for get_extraction_method function."""

    def test_returns_requirements_txt_for_requirements_file(self):
        """Should return requirements_txt for requirements.txt files."""
        assert get_extraction_method("requirements.txt", None) == "requirements_txt"
        assert get_extraction_method("dev-requirements.txt", None) == "requirements_txt"
        assert get_extraction_method("path/to/requirements.txt", None) == "requirements_txt"

    def test_returns_pyproject_toml_for_pyproject(self):
        """Should return pyproject_toml for pyproject.toml files."""
        assert get_extraction_method("pyproject.toml", None) == "pyproject_toml"
        assert get_extraction_method("path/to/pyproject.toml", None) == "pyproject_toml"

    def test_returns_package_json_for_package_json(self):
        """Should return package_json for package.json files."""
        assert get_extraction_method("package.json", None) == "package_json"
        assert get_extraction_method("path/to/package.json", None) == "package_json"

    def test_returns_treesitter_for_supported_languages(self):
        """Should return treesitter for Python, JS, TS, Java, C#."""
        assert get_extraction_method("main.py", "python") == "treesitter"
        assert get_extraction_method("app.js", "javascript") == "treesitter"
        assert get_extraction_method("app.ts", "typescript") == "treesitter"
        assert get_extraction_method("Main.java", "java") == "treesitter"
        assert get_extraction_method("Main.cs", "csharp") == "treesitter"

    def test_returns_llm_for_unsupported_files(self):
        """Should return llm for unsupported file types."""
        assert get_extraction_method("config.yaml", "yaml") == "llm"
        assert get_extraction_method("readme.md", "markdown") == "llm"
        assert get_extraction_method("main.rb", "ruby") == "llm"

    def test_case_insensitive_filename(self):
        """Should handle different cases in filenames."""
        assert get_extraction_method("REQUIREMENTS.TXT", None) == "requirements_txt"
        assert get_extraction_method("PACKAGE.JSON", None) == "package_json"


# =============================================================================
# parse_requirement_line Tests
# =============================================================================


class TestParseRequirementLine:
    """Tests for parse_requirement_line function."""

    def test_parses_simple_requirement(self):
        """Should parse simple package name."""
        result = parse_requirement_line("flask")
        assert result is not None
        assert result["name"] == "flask"
        assert result["version"] is None

    def test_parses_requirement_with_version(self):
        """Should parse package with version constraint."""
        result = parse_requirement_line("flask>=2.0.0")
        assert result is not None
        assert result["name"] == "flask"
        assert result["version"] is not None
        assert "2.0.0" in result["version"]

    def test_parses_requirement_with_extras(self):
        """Should parse package with extras."""
        result = parse_requirement_line("flask[async]>=2.0")
        assert result is not None
        assert result["name"] == "flask"

    def test_parses_url_based_requirement(self):
        """Should parse URL-based requirements."""
        result = parse_requirement_line("package @ https://example.com/package.tar.gz")
        assert result is not None
        assert result["name"] == "package"
        assert result["version"] is None

    def test_parses_requirement_with_environment_marker(self):
        """Should parse requirement with environment marker."""
        result = parse_requirement_line("pywin32; sys_platform == 'win32'")
        assert result is not None
        assert result["name"] == "pywin32"

    def test_returns_none_for_empty_line(self):
        """Should return None for empty lines."""
        assert parse_requirement_line("") is None
        assert parse_requirement_line("   ") is None

    def test_returns_none_for_invalid_line(self):
        """Should return None for invalid package name format."""
        assert parse_requirement_line("!!!invalid") is None


# =============================================================================
# _extract_from_requirements_txt Tests
# =============================================================================


class TestExtractFromRequirementsTxt:
    """Tests for _extract_from_requirements_txt function."""

    def test_extracts_dependencies(self):
        """Should extract dependencies from requirements.txt."""
        content = """
flask>=2.0.0
django==4.0
requests
"""
        result = _extract_from_requirements_txt("requirements.txt", content, "test-repo")

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 3
        assert len(result["data"]["edges"]) == 3

    def test_skips_comments(self):
        """Should skip comment lines."""
        content = """
# This is a comment
flask>=2.0.0
# Another comment
django
"""
        result = _extract_from_requirements_txt("requirements.txt", content, "test-repo")

        assert len(result["data"]["nodes"]) == 2

    def test_skips_flags(self):
        """Should skip lines starting with dash (flags)."""
        content = """
-r other-requirements.txt
-e .
flask
"""
        result = _extract_from_requirements_txt("requirements.txt", content, "test-repo")

        assert len(result["data"]["nodes"]) == 1

    def test_deduplicates_dependencies(self):
        """Should deduplicate same dependency name."""
        content = """
flask>=2.0.0
Flask==2.1.0
FLASK
"""
        result = _extract_from_requirements_txt("requirements.txt", content, "test-repo")

        # Should only have 1 node (all "flask" variations)
        assert len(result["data"]["nodes"]) == 1

    def test_creates_uses_edges(self):
        """Should create USES edges from file to dependency."""
        content = "flask>=2.0.0"
        result = _extract_from_requirements_txt("requirements.txt", content, "test-repo")

        assert len(result["data"]["edges"]) == 1
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "USES"


# =============================================================================
# _extract_from_pyproject_toml Tests
# =============================================================================


class TestExtractFromPyprojectToml:
    """Tests for _extract_from_pyproject_toml function."""

    def test_extracts_dependencies(self):
        """Should extract dependencies from pyproject.toml."""
        content = """
[project]
dependencies = [
    "flask>=2.0",
    "django>=4.0",
]
"""
        result = _extract_from_pyproject_toml("pyproject.toml", content, "test-repo")

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 2

    def test_handles_multiple_dependency_sections(self):
        """Should handle multiple dependency arrays."""
        content = """
[project]
dependencies = ["flask", "django"]

[tool.poetry.dependencies]
dependencies = ["requests"]
"""
        result = _extract_from_pyproject_toml("pyproject.toml", content, "test-repo")

        assert result["success"] is True
        assert len(result["data"]["nodes"]) >= 2

    def test_handles_single_quotes(self):
        """Should handle single-quoted dependencies."""
        content = """
[project]
dependencies = [
    'flask',
    'django',
]
"""
        result = _extract_from_pyproject_toml("pyproject.toml", content, "test-repo")

        assert len(result["data"]["nodes"]) == 2


# =============================================================================
# _extract_from_package_json Tests
# =============================================================================


class TestExtractFromPackageJson:
    """Tests for _extract_from_package_json function."""

    def test_extracts_dependencies(self):
        """Should extract dependencies from package.json."""
        content = """
{
    "dependencies": {
        "express": "^4.18.0",
        "lodash": "^4.17.0"
    }
}
"""
        result = _extract_from_package_json("package.json", content, "test-repo")

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 2

    def test_extracts_dev_dependencies(self):
        """Should extract devDependencies."""
        content = """
{
    "devDependencies": {
        "jest": "^29.0.0",
        "typescript": "^5.0.0"
    }
}
"""
        result = _extract_from_package_json("package.json", content, "test-repo")

        assert len(result["data"]["nodes"]) == 2

    def test_combines_all_dependencies(self):
        """Should combine dependencies and devDependencies."""
        content = """
{
    "dependencies": {"express": "^4.18.0"},
    "devDependencies": {"jest": "^29.0.0"}
}
"""
        result = _extract_from_package_json("package.json", content, "test-repo")

        assert len(result["data"]["nodes"]) == 2

    def test_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        content = "not valid json"
        result = _extract_from_package_json("package.json", content, "test-repo")

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_sets_npm_ecosystem(self):
        """Should set ecosystem to npm."""
        content = '{"dependencies": {"express": "^4.18.0"}}'
        result = _extract_from_package_json("package.json", content, "test-repo")

        node = result["data"]["nodes"][0]
        assert node["properties"]["ecosystem"] == "npm"


# =============================================================================
# build_external_dependency_node Tests
# =============================================================================


class TestBuildExternalDependencyNode:
    """Tests for build_external_dependency_node function."""

    def test_builds_valid_node(self):
        """Should build valid node from dependency data."""
        dep_data = {
            "dependencyName": "flask",
            "dependencyCategory": "library",
            "version": "2.0.0",
            "ecosystem": "pypi",
            "description": "Web framework",
            "confidence": 0.9,
        }

        result = build_external_dependency_node(dep_data, "app.py", "test-repo")

        assert result["success"] is True
        assert result["data"]["label"] == "ExternalDependency"
        assert result["data"]["properties"]["dependencyName"] == "flask"

    def test_validates_required_fields(self):
        """Should fail when required fields are missing."""
        dep_data = {
            "dependencyName": "flask",
            # Missing other required fields
        }

        result = build_external_dependency_node(dep_data, "app.py", "test-repo")

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_normalizes_invalid_category(self):
        """Should normalize invalid category to 'library'."""
        dep_data = {
            "dependencyName": "test",
            "dependencyCategory": "INVALID",
            "version": "1.0",
            "ecosystem": "pypi",
            "description": "Test",
            "confidence": 0.9,
        }

        result = build_external_dependency_node(dep_data, "app.py", "test-repo")

        assert result["success"] is True
        assert result["data"]["properties"]["dependencyCategory"] == "library"


# =============================================================================
# build_extraction_prompt Tests
# =============================================================================


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_file_path(self):
        """Should include file path in prompt."""
        prompt = build_extraction_prompt("content", "src/app.py", "instruction", "{}", PROMPT_TEXTS)

        assert "src/app.py" in prompt

    def test_includes_file_content(self):
        """Should include file content in prompt."""
        prompt = build_extraction_prompt("import flask", "app.py", "instr", "{}", PROMPT_TEXTS)

        assert "import flask" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_extraction_prompt("content", "app.py", "Find dependencies", "{}", PROMPT_TEXTS)

        assert "Find dependencies" in prompt


# =============================================================================
# parse_llm_response Tests
# =============================================================================


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_parses_valid_json(self):
        """Should parse valid JSON response."""
        response = (
            '{"dependencies": [{"dependencyName": "flask", '
            '"dependencyCategory": "library", "version": "2.0", '
            '"ecosystem": "pypi", "description": "Web framework", "confidence": 0.9}]}'
        )

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["dependencyName"] == "flask"

    def test_handles_empty_dependencies(self):
        """Should handle empty dependencies array."""
        response = '{"dependencies": []}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 0

    def test_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "not valid json"

        result = parse_llm_response(response)

        assert result["success"] is False


# =============================================================================
# _build_result Tests
# =============================================================================


class TestBuildResult:
    """Tests for _build_result function."""

    def test_builds_success_result(self):
        """Should build successful result."""
        nodes = [{"node_id": "1"}]
        edges = [{"edge_id": "2"}]

        result = _build_result(nodes, edges, [], "deterministic")

        assert result["success"] is True
        assert result["data"]["nodes"] == nodes
        assert result["data"]["edges"] == edges
        assert result["stats"]["extraction_method"] == "deterministic"

    def test_builds_failure_result_with_errors(self):
        """Should build failure result when errors present and no nodes."""
        result = _build_result([], [], ["Error occurred"], "llm")

        assert result["success"] is False
        assert "Error occurred" in result["errors"]


# =============================================================================
# _build_dependency_node_and_edge Tests
# =============================================================================


class TestBuildDependencyNodeAndEdge:
    """Tests for _build_dependency_node_and_edge function."""

    def test_builds_node_and_edge(self):
        """Should build node and edge correctly."""
        node, edge = _build_dependency_node_and_edge(
            name="flask",
            version="2.0.0",
            ecosystem="pypi",
            origin_source="requirements.txt",
            repo_name="test-repo",
            file_node_id="file::test-repo::requirements.txt",
            extraction_method="deterministic",
        )

        assert node["label"] == "ExternalDependency"
        assert node["properties"]["dependencyName"] == "flask"
        assert node["properties"]["version"] == "2.0.0"
        assert node["properties"]["ecosystem"] == "pypi"
        assert edge["relationship_type"] == "USES"

    def test_handles_none_version(self):
        """Should handle None version."""
        node, _edge = _build_dependency_node_and_edge(
            name="flask",
            version=None,
            ecosystem="pypi",
            origin_source="app.py",
            repo_name="test-repo",
            file_node_id="file::test-repo::app.py",
            extraction_method="ast",
        )

        assert node["properties"]["version"] is None


# =============================================================================
# extract_external_dependencies Tests
# =============================================================================


class TestExtractExternalDependencies:
    """Tests for extract_external_dependencies function."""

    def test_uses_deterministic_for_requirements_txt(self):
        """Should use deterministic extraction for requirements.txt."""
        result = extract_external_dependencies(
            file_path="requirements.txt",
            file_content="flask>=2.0.0\ndjango",
            repo_name="test-repo",
            subtype=None,
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert result["stats"]["extraction_method"] == "deterministic"

    def test_uses_deterministic_for_package_json(self):
        """Should use deterministic extraction for package.json."""
        result = extract_external_dependencies(
            file_path="package.json",
            file_content='{"dependencies": {"express": "^4.0"}}',
            repo_name="test-repo",
            subtype=None,
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert result["stats"]["extraction_method"] == "deterministic"

    def test_uses_treesitter_for_python(self):
        """Should use tree-sitter extraction for Python files."""
        result = extract_external_dependencies(
            file_path="app.py",
            file_content="import flask\nimport django",
            repo_name="test-repo",
            subtype="python",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert result["stats"]["extraction_method"] == "treesitter"

    def test_filters_stdlib_imports(self):
        """Should filter out standard library imports."""
        result = extract_external_dependencies(
            file_path="app.py",
            file_content="import os\nimport sys\nimport flask",
            repo_name="test-repo",
            subtype="python",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        # Only flask should be extracted (os and sys are stdlib)
        assert len(result["data"]["nodes"]) == 1
        assert result["data"]["nodes"][0]["properties"]["dependencyName"] == "flask"


# =============================================================================
# extract_external_dependencies_batch Tests
# =============================================================================


class TestExtractExternalDependenciesBatch:
    """Tests for extract_external_dependencies_batch function."""

    def test_processes_all_files(self):
        """Should process all files in batch."""
        files: list[dict[str, str]] = [
            {"path": "requirements.txt", "content": "flask>=2.0", "subtype": ""},
            {"path": "package.json", "content": '{"dependencies": {"express": "^4.0"}}', "subtype": ""},
        ]

        result = extract_external_dependencies_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["stats"]["files_processed"] == 2
        assert result["success"] is True

    def test_calls_progress_callback(self):
        """Should call progress callback for each file."""
        progress_calls: list[tuple[int, int, str]] = []

        def callback(current: int, total: int, path: str) -> None:
            progress_calls.append((current, total, path))

        files: list[dict[str, str]] = [
            {"path": "requirements.txt", "content": "flask", "subtype": ""},
            {"path": "other.txt", "content": "x", "subtype": ""},
        ]

        extract_external_dependencies_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
            progress_callback=callback,
        )

        assert len(progress_calls) == 2

    def test_aggregates_results(self):
        """Should aggregate nodes and edges from all files."""
        files: list[dict[str, str]] = [
            {"path": "requirements.txt", "content": "flask", "subtype": ""},
            {"path": "package.json", "content": '{"dependencies": {"express": "^4.0"}}', "subtype": ""},
        ]

        result = extract_external_dependencies_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["stats"]["total_nodes"] >= 2
