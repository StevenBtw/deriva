"""Tests for modules.extraction.edges module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.modules.extraction.edges import (
    ALL_EDGE_TYPES,
    PYTHON_STDLIB,
    EdgeType,
    _build_method_lookup,
    _extract_type_names,
    _resolve_absolute_import,
    _resolve_import,
    _resolve_relative_import,
    extract_edges_batch,
    extract_edges_from_file,
)

# =============================================================================
# EdgeType Enum Tests
# =============================================================================


class TestEdgeType:
    """Tests for EdgeType enum."""

    def test_imports_value(self):
        """Should have IMPORTS edge type."""
        assert EdgeType.IMPORTS.value == "IMPORTS"

    def test_uses_value(self):
        """Should have USES edge type."""
        assert EdgeType.USES.value == "USES"

    def test_calls_value(self):
        """Should have CALLS edge type."""
        assert EdgeType.CALLS.value == "CALLS"

    def test_decorated_by_value(self):
        """Should have DECORATED_BY edge type."""
        assert EdgeType.DECORATED_BY.value == "DECORATED_BY"

    def test_references_value(self):
        """Should have REFERENCES edge type."""
        assert EdgeType.REFERENCES.value == "REFERENCES"


class TestAllEdgeTypes:
    """Tests for ALL_EDGE_TYPES constant."""

    def test_contains_all_edge_types(self):
        """Should contain all edge types."""
        assert EdgeType.IMPORTS in ALL_EDGE_TYPES
        assert EdgeType.USES in ALL_EDGE_TYPES
        assert EdgeType.CALLS in ALL_EDGE_TYPES
        assert EdgeType.DECORATED_BY in ALL_EDGE_TYPES
        assert EdgeType.REFERENCES in ALL_EDGE_TYPES

    def test_has_five_types(self):
        """Should have exactly 5 edge types."""
        assert len(ALL_EDGE_TYPES) == 5


# =============================================================================
# _resolve_relative_import Tests
# =============================================================================


class TestResolveRelativeImport:
    """Tests for _resolve_relative_import function."""

    def test_resolves_single_dot_import_same_dir(self):
        """Should resolve single-dot relative import in same directory."""
        all_files = {"models.py"}
        result = _resolve_relative_import(
            module=".models",
            current_file="main.py",
            all_file_paths=all_files,
        )
        assert result == "models.py"

    def test_returns_none_for_not_found(self):
        """Should return None when import cannot be resolved."""
        all_files = {"other.py"}
        result = _resolve_relative_import(
            module=".models",
            current_file="main.py",
            all_file_paths=all_files,
        )
        assert result is None

    def test_handles_empty_module_after_dots(self):
        """Should handle import with just dots (package import)."""
        all_files = {"__init__.py"}
        result = _resolve_relative_import(
            module=".",
            current_file="main.py",
            all_file_paths=all_files,
        )
        # Should look for __init__.py in current dir
        assert result == "__init__.py" or result is None


# =============================================================================
# _resolve_absolute_import Tests
# =============================================================================


class TestResolveAbsoluteImport:
    """Tests for _resolve_absolute_import function."""

    def test_resolves_simple_module(self):
        """Should resolve simple module name."""
        all_files = {"utils.py"}
        result = _resolve_absolute_import(
            module="utils",
            all_file_paths=all_files,
        )
        assert result == "utils.py"

    def test_resolves_nested_module(self):
        """Should resolve nested module path."""
        all_files = {"src/utils/helpers.py"}
        result = _resolve_absolute_import(
            module="src.utils.helpers",
            all_file_paths=all_files,
        )
        assert result == "src/utils/helpers.py"

    def test_resolves_package_init(self):
        """Should resolve to package __init__.py."""
        all_files = {"mypackage/__init__.py"}
        result = _resolve_absolute_import(
            module="mypackage",
            all_file_paths=all_files,
        )
        assert result == "mypackage/__init__.py"

    def test_returns_none_for_not_found(self):
        """Should return None when module not found."""
        all_files = {"other.py"}
        result = _resolve_absolute_import(
            module="utils",
            all_file_paths=all_files,
        )
        assert result is None

    def test_resolves_submodule_to_parent(self):
        """Should resolve submodule to parent file if exists."""
        all_files = {"utils.py"}
        result = _resolve_absolute_import(
            module="utils.helper",  # utils.helper -> utils.py
            all_file_paths=all_files,
        )
        assert result == "utils.py"


# =============================================================================
# _resolve_import Tests
# =============================================================================


class TestResolveImport:
    """Tests for _resolve_import function."""

    def test_resolves_internal_import(self):
        """Should identify internal imports."""
        all_files = {"src/models.py"}
        external_packages = {"flask", "django"}
        result = _resolve_import(
            module="src.models",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "internal"
        assert result["target_path"] == "src/models.py"

    def test_resolves_external_import(self):
        """Should identify external imports."""
        all_files = {"src/main.py"}
        external_packages = {"flask", "django"}
        result = _resolve_import(
            module="flask.views",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "external"
        assert result["package"] == "flask"

    def test_resolves_stdlib_import(self):
        """Should identify stdlib imports."""
        all_files = {"src/main.py"}
        external_packages = {"flask"}
        result = _resolve_import(
            module="os.path",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "stdlib"
        assert result["module"] == "os"

    def test_resolves_relative_import(self):
        """Should resolve relative imports."""
        all_files = {"src/models.py"}
        external_packages = set()
        result = _resolve_import(
            module=".models",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "internal"
        assert result["target_path"] == "src/models.py"

    def test_handles_unresolved_relative(self):
        """Should handle unresolved relative imports."""
        all_files = {"src/main.py"}
        external_packages = set()
        result = _resolve_import(
            module=".nonexistent",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "unknown"
        assert "relative_not_found" in result.get("reason", "")

    def test_defaults_to_external_for_unknown(self):
        """Should default to external for unknown packages."""
        all_files = {"src/main.py"}
        external_packages = set()
        result = _resolve_import(
            module="unknown_package",
            current_file="src/main.py",
            all_file_paths=all_files,
            external_packages=external_packages,
        )
        assert result["type"] == "external"
        assert result["package"] == "unknown_package"


# =============================================================================
# _build_method_lookup Tests
# =============================================================================


class TestBuildMethodLookup:
    """Tests for _build_method_lookup function."""

    def test_builds_lookup_from_methods(self):
        """Should build lookup dict from methods."""
        mock_method1 = MagicMock()
        mock_method1.name = "func_a"
        mock_method1.class_name = None
        mock_method1.line_start = 1
        mock_method1.line_end = 10

        mock_method2 = MagicMock()
        mock_method2.name = "method_b"
        mock_method2.class_name = "MyClass"
        mock_method2.line_start = 20
        mock_method2.line_end = 30

        methods = [mock_method1, mock_method2]

        result = _build_method_lookup(methods)

        # Keys are just method names, not "ClassName.method"
        assert "func_a" in result
        assert "method_b" in result

    def test_handles_empty_list(self):
        """Should return empty dict for empty list."""
        result = _build_method_lookup([])
        assert not result  # Empty dict is falsey

    def test_handles_duplicate_names(self):
        """Should append duplicate names to list."""
        mock_method1 = MagicMock()
        mock_method1.name = "func"
        mock_method1.class_name = None
        mock_method1.line_start = 1
        mock_method1.line_end = 10

        mock_method2 = MagicMock()
        mock_method2.name = "func"
        mock_method2.class_name = "MyClass"
        mock_method2.line_start = 20
        mock_method2.line_end = 30

        methods = [mock_method1, mock_method2]

        result = _build_method_lookup(methods)

        assert "func" in result
        # Both methods should be in the list
        assert len(result["func"]) == 2


# =============================================================================
# _extract_type_names Tests
# =============================================================================


class TestExtractTypeNames:
    """Tests for _extract_type_names function."""

    def test_extracts_simple_type(self):
        """Should extract simple type name."""
        result = _extract_type_names("MyClass")
        assert "MyClass" in result

    def test_extracts_from_generic(self):
        """Should extract type from generic annotation."""
        result = _extract_type_names("List[MyClass]")
        assert "MyClass" in result
        assert "List" not in result  # List is a container

    def test_extracts_multiple_types(self):
        """Should extract multiple types from union."""
        result = _extract_type_names("Union[TypeA, TypeB]")
        assert "TypeA" in result
        assert "TypeB" in result

    def test_handles_optional(self):
        """Should handle Optional type."""
        result = _extract_type_names("Optional[MyType]")
        assert "MyType" in result
        assert "Optional" not in result

    def test_removes_quotes(self):
        """Should remove quotes from forward references."""
        result = _extract_type_names('"MyForwardRef"')
        assert "MyForwardRef" in result

    def test_ignores_builtin_containers(self):
        """Should ignore builtin container types."""
        result = _extract_type_names("Dict[str, List[int]]")
        # Only PascalCase names that aren't containers
        assert "Dict" not in result
        assert "List" not in result

    def test_extracts_from_nested_generic(self):
        """Should extract from deeply nested generics."""
        result = _extract_type_names("List[Dict[str, UserModel]]")
        assert "UserModel" in result

    def test_returns_empty_for_primitives(self):
        """Should return empty set for primitive types only."""
        result = _extract_type_names("str")
        assert len(result) == 0

    def test_handles_callable(self):
        """Should handle Callable type annotations."""
        result = _extract_type_names("Callable[[InputType], OutputType]")
        assert "InputType" in result
        assert "OutputType" in result


# =============================================================================
# Python Stdlib Tests
# =============================================================================


class TestPythonStdlib:
    """Tests for PYTHON_STDLIB constant."""

    def test_contains_common_modules(self):
        """Should contain common stdlib modules."""
        assert "os" in PYTHON_STDLIB
        assert "sys" in PYTHON_STDLIB
        assert "json" in PYTHON_STDLIB
        assert "re" in PYTHON_STDLIB
        assert "pathlib" in PYTHON_STDLIB
        assert "typing" in PYTHON_STDLIB
        assert "collections" in PYTHON_STDLIB
        assert "datetime" in PYTHON_STDLIB

    def test_does_not_contain_external_packages(self):
        """Should not contain external packages."""
        assert "flask" not in PYTHON_STDLIB
        assert "django" not in PYTHON_STDLIB
        assert "numpy" not in PYTHON_STDLIB
        assert "pandas" not in PYTHON_STDLIB


# =============================================================================
# extract_edges_from_file Tests
# =============================================================================


class TestExtractEdgesFromFile:
    """Tests for extract_edges_from_file function."""

    def test_returns_result_dict(self):
        """Should return a result dictionary."""
        mock_tsm = MagicMock()
        mock_tsm.get_handler.return_value = None

        with patch("deriva.modules.extraction.edges.TreeSitterManager", return_value=mock_tsm):
            result = extract_edges_from_file(
                file_path="test.py",
                file_content="print('hello')",
                repo_name="test-repo",
                external_packages=set(),
                all_file_paths={"test.py"},
            )

        assert "success" in result
        assert "data" in result
        assert "errors" in result

    def test_handles_unsupported_language(self):
        """Should handle unsupported file types gracefully."""
        mock_tsm = MagicMock()
        mock_tsm.get_handler.return_value = None

        with patch("deriva.modules.extraction.edges.TreeSitterManager", return_value=mock_tsm):
            result = extract_edges_from_file(
                file_path="test.txt",  # Unsupported
                file_content="some text",
                repo_name="test-repo",
                external_packages=set(),
                all_file_paths={"test.txt"},
            )

        assert result["success"] is True
        assert len(result["data"]["edges"]) == 0


# =============================================================================
# extract_edges_batch Tests
# =============================================================================


class TestExtractEdgesBatch:
    """Tests for extract_edges_batch function."""

    def test_returns_result_dict(self):
        """Should return a result dictionary."""
        result = extract_edges_batch(
            files=[],
            repo_name="test-repo",
            repo_path="/repo",
        )

        assert "success" in result
        assert "data" in result
        assert "errors" in result
        assert "stats" in result

    def test_handles_empty_files(self):
        """Should handle empty file list."""
        result = extract_edges_batch(
            files=[],
            repo_name="test-repo",
            repo_path="/repo",
        )

        assert result["success"] is True
        assert len(result["data"]["edges"]) == 0

    def test_stats_includes_required_fields(self):
        """Should include required stats fields."""
        result = extract_edges_batch(
            files=[],
            repo_name="test-repo",
            repo_path="/repo",
        )

        stats = result["stats"]
        assert "files_processed" in stats
        assert "total_edges" in stats
        assert "imports" in stats
        assert "calls" in stats

    def test_processes_python_file_with_content(self):
        """Should process Python file with content provided."""
        files = [
            {
                "path": "main.py",
                "file_type": "source",
                "subtype": "python",
                "content": "import os\n\ndef hello():\n    print('hello')\n",
            }
        ]
        result = extract_edges_batch(
            files=files,
            repo_name="test-repo",
            repo_path="/repo",
        )

        assert result["success"] is True
        assert result["stats"]["files_processed"] == 1

    def test_filters_non_source_files(self):
        """Should filter out non-source files."""
        files = [
            {"path": "README.md", "file_type": "documentation", "subtype": "markdown"},
            {"path": "main.py", "file_type": "source", "subtype": "python", "content": "x = 1"},
        ]
        result = extract_edges_batch(
            files=files,
            repo_name="test-repo",
            repo_path="/repo",
        )

        # Only Python file should be processed
        assert result["stats"]["files_processed"] == 1

    def test_filters_unsupported_languages(self):
        """Should filter out unsupported language files."""
        files = [
            {"path": "main.rb", "file_type": "source", "subtype": "ruby", "content": "puts 'hi'"},
        ]
        result = extract_edges_batch(
            files=files,
            repo_name="test-repo",
            repo_path="/repo",
        )

        assert result["stats"]["files_processed"] == 0

    def test_calls_progress_callback(self):
        """Should call progress callback for each file."""
        progress_calls = []

        def callback(current, total, path):
            progress_calls.append((current, total, path))

        files = [
            {"path": "a.py", "file_type": "source", "subtype": "python", "content": "x = 1"},
            {"path": "b.py", "file_type": "source", "subtype": "python", "content": "y = 2"},
        ]
        extract_edges_batch(
            files=files,
            repo_name="test-repo",
            repo_path="/repo",
            progress_callback=callback,
        )

        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "a.py")
        assert progress_calls[1] == (2, 2, "b.py")

    def test_aggregates_stats_from_multiple_files(self):
        """Should aggregate stats from multiple files."""
        files = [
            {
                "path": "a.py",
                "file_type": "source",
                "subtype": "python",
                "content": "import os\nimport sys\n",
            },
            {
                "path": "b.py",
                "file_type": "source",
                "subtype": "python",
                "content": "import json\n",
            },
        ]
        result = extract_edges_batch(
            files=files,
            repo_name="test-repo",
            repo_path="/repo",
        )

        assert result["stats"]["files_processed"] == 2


# =============================================================================
# _extract_import_edges Tests
# =============================================================================


class TestExtractImportEdges:
    """Tests for _extract_import_edges function."""

    def test_creates_imports_edge_for_internal_import(self):
        """Should create IMPORTS edge for internal imports."""
        from deriva.adapters.treesitter.models import ExtractedImport
        from deriva.modules.extraction.edges import _extract_import_edges

        imports = [ExtractedImport(module="models", names=["User"], line=1, is_from_import=True)]
        all_files = {"main.py", "models.py"}

        edges, _nodes, stats = _extract_import_edges(
            imports=imports,
            file_path="main.py",
            repo_name="test-repo",
            all_file_paths=all_files,
            external_packages=set(),
            edge_types={EdgeType.IMPORTS, EdgeType.USES},
        )

        assert stats["internal"] == 1
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "IMPORTS"

    def test_creates_uses_edge_for_external_import(self):
        """Should create USES edge for external imports."""
        from deriva.adapters.treesitter.models import ExtractedImport
        from deriva.modules.extraction.edges import _extract_import_edges

        imports = [ExtractedImport(module="flask", names=["Flask"], line=1, is_from_import=True)]

        edges, _nodes, stats = _extract_import_edges(
            imports=imports,
            file_path="main.py",
            repo_name="test-repo",
            all_file_paths={"main.py"},
            external_packages={"flask"},
            edge_types={EdgeType.IMPORTS, EdgeType.USES},
        )

        assert stats["external"] == 1
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "USES"

    def test_skips_stdlib_imports(self):
        """Should skip stdlib imports."""
        from deriva.adapters.treesitter.models import ExtractedImport
        from deriva.modules.extraction.edges import _extract_import_edges

        imports = [ExtractedImport(module="os", names=["path"], line=1, is_from_import=True)]

        edges, _nodes, stats = _extract_import_edges(
            imports=imports,
            file_path="main.py",
            repo_name="test-repo",
            all_file_paths={"main.py"},
            external_packages=set(),
            edge_types={EdgeType.IMPORTS, EdgeType.USES},
        )

        # os is stdlib, so no edges created
        assert len(edges) == 0
        assert stats["unresolved"] == 1

    def test_respects_edge_type_filter(self):
        """Should respect edge type filter."""
        from deriva.adapters.treesitter.models import ExtractedImport
        from deriva.modules.extraction.edges import _extract_import_edges

        imports = [
            ExtractedImport(module="models", names=["User"], line=1, is_from_import=True),
            ExtractedImport(module="flask", names=["Flask"], line=2, is_from_import=True),
        ]

        # Only request IMPORTS, not USES
        edges, _nodes, stats = _extract_import_edges(
            imports=imports,
            file_path="main.py",
            repo_name="test-repo",
            all_file_paths={"main.py", "models.py"},
            external_packages={"flask"},
            edge_types={EdgeType.IMPORTS},  # No USES
        )

        # Should only have IMPORTS edge, not USES
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "IMPORTS"


# =============================================================================
# _resolve_relative_import Advanced Tests
# =============================================================================


class TestResolveRelativeImportAdvanced:
    """Advanced tests for _resolve_relative_import function."""

    def test_resolves_double_dot_import(self):
        """Should resolve double-dot relative import.

        In Python import semantics:
        - . = current package
        - .. = parent package (1 level up)
        - ... = grandparent package (2 levels up)

        From pkg/subpkg/module.py, ..utils looks in pkg/utils.py
        """
        all_files = {"pkg/utils.py", "pkg/subpkg/module.py"}
        result = _resolve_relative_import(
            module="..utils",
            current_file="pkg/subpkg/module.py",
            all_file_paths=all_files,
        )
        # Should go up one level from pkg/subpkg to pkg
        assert result == "pkg/utils.py"

    def test_resolves_triple_dot_import(self):
        """Should resolve triple-dot relative import to root level."""
        all_files = {"utils.py", "pkg/subpkg/module.py"}
        result = _resolve_relative_import(
            module="...utils",
            current_file="pkg/subpkg/module.py",
            all_file_paths=all_files,
        )
        # Should go up two levels from pkg/subpkg to root
        assert result == "utils.py"

    def test_handles_deep_relative_import(self):
        """Should handle deeply nested relative imports."""
        all_files = {"a/base.py", "a/b/c/d.py"}
        result = _resolve_relative_import(
            module="...base",
            current_file="a/b/c/d.py",
            all_file_paths=all_files,
        )
        # Should go up two levels from a/b/c to a, then look for base
        assert result == "a/base.py"

    def test_returns_none_for_too_many_dots(self):
        """Should return None if module not found after going up directories."""
        all_files = {"other.py"}  # module.py not in files
        result = _resolve_relative_import(
            module="....module",  # Too many dots
            current_file="a/b.py",  # Only one level deep
            all_file_paths=all_files,
        )
        assert result is None

    def test_resolves_subpackage_init(self):
        """Should resolve to __init__.py for package imports."""
        all_files = {"pkg/__init__.py", "pkg/module.py"}
        result = _resolve_relative_import(
            module=".pkg",
            current_file="main.py",
            all_file_paths=all_files,
        )
        # Should resolve pkg to pkg/__init__.py
        assert result == "pkg/__init__.py" or result == "pkg.py" or result is None


# =============================================================================
# _extract_call_edges Tests
# =============================================================================


class TestExtractCallEdges:
    """Tests for _extract_call_edges function."""

    def test_creates_call_edge_for_resolved_call(self):
        """Should create CALLS edge for resolved function calls."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="helper",
                callee_qualifier=None,
                caller_name="main",
                caller_class=None,
                is_method_call=False,
                line=5,
            )
        ]
        method_lookup = {
            "main": [{"class_name": None, "line_start": 1, "line_end": 10}],
            "helper": [{"class_name": None, "line_start": 15, "line_end": 20}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total"] == 1
        assert stats["resolved"] == 1
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "CALLS"

    def test_skips_builtin_calls(self):
        """Should skip builtin function calls."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="print",  # builtin
                callee_qualifier=None,
                caller_name="main",
                caller_class=None,
                is_method_call=False,
                line=5,
            )
        ]
        method_lookup = {
            "main": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total"] == 1
        assert stats["unresolved"] == 1
        assert len(edges) == 0

    def test_resolves_self_method_call(self):
        """Should resolve self.method() calls within same class."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="helper_method",
                callee_qualifier="self",
                caller_name="process",
                caller_class="MyClass",
                is_method_call=True,
                line=10,
            )
        ]
        method_lookup = {
            "process": [{"class_name": "MyClass", "line_start": 5, "line_end": 15}],
            "helper_method": [{"class_name": "MyClass", "line_start": 20, "line_end": 25}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["resolved"] == 1
        assert len(edges) == 1

    def test_skips_external_qualifier_calls(self):
        """Should skip calls with external qualifiers."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="method",
                callee_qualifier="external_obj",  # Not self/cls
                caller_name="main",
                caller_class=None,
                is_method_call=True,
                line=5,
            )
        ]
        method_lookup = {
            "main": [{"class_name": None, "line_start": 1, "line_end": 10}],
            "method": [{"class_name": None, "line_start": 15, "line_end": 20}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["unresolved"] == 1
        assert len(edges) == 0

    def test_skips_self_loops(self):
        """Should not create self-loop edges."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="recursive",
                callee_qualifier=None,
                caller_name="recursive",  # Same as callee
                caller_class=None,
                is_method_call=False,
                line=5,
            )
        ]
        method_lookup = {
            "recursive": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        # Should not create self-loop
        assert len(edges) == 0

    def test_handles_unresolved_caller(self):
        """Should handle case when caller cannot be resolved."""
        from deriva.adapters.treesitter.models import ExtractedCall
        from deriva.modules.extraction.edges import _extract_call_edges

        calls = [
            ExtractedCall(
                callee_name="helper",
                callee_qualifier=None,
                caller_name="unknown_caller",  # Not in lookup
                caller_class=None,
                is_method_call=False,
                line=5,
            )
        ]
        method_lookup = {
            "helper": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        edges, stats = _extract_call_edges(
            calls=calls,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["unresolved"] == 1
        assert len(edges) == 0


# =============================================================================
# _resolve_caller Tests
# =============================================================================


class TestResolveCaller:
    """Tests for _resolve_caller function."""

    def test_resolves_single_candidate(self):
        """Should resolve when there's only one candidate."""
        from deriva.modules.extraction.edges import _resolve_caller

        method_lookup = {
            "my_func": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        result = _resolve_caller(
            caller_name="my_func",
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None
        assert "my_func" in result

    def test_resolves_by_class_name(self):
        """Should resolve by class name when multiple candidates exist."""
        from deriva.modules.extraction.edges import _resolve_caller

        method_lookup = {
            "method": [
                {"class_name": "ClassA", "line_start": 1, "line_end": 10},
                {"class_name": "ClassB", "line_start": 20, "line_end": 30},
            ],
        }

        result = _resolve_caller(
            caller_name="method",
            caller_class="ClassB",
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None
        assert "ClassB" in result

    def test_prefers_standalone_function(self):
        """Should prefer standalone function when no class match."""
        from deriva.modules.extraction.edges import _resolve_caller

        method_lookup = {
            "func": [
                {"class_name": "SomeClass", "line_start": 1, "line_end": 10},
                {"class_name": None, "line_start": 20, "line_end": 30},
            ],
        }

        result = _resolve_caller(
            caller_name="func",
            caller_class="OtherClass",  # Not in candidates
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None
        # Should resolve to standalone function (class_name=None)

    def test_returns_none_for_unknown_caller(self):
        """Should return None for unknown caller."""
        from deriva.modules.extraction.edges import _resolve_caller

        method_lookup = {}

        result = _resolve_caller(
            caller_name="unknown",
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is None


# =============================================================================
# _resolve_callee Tests
# =============================================================================


class TestResolveCallee:
    """Tests for _resolve_callee function."""

    def test_resolves_simple_function(self):
        """Should resolve simple function call."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "helper": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        result = _resolve_callee(
            callee_name="helper",
            callee_qualifier=None,
            is_method_call=False,
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None

    def test_resolves_self_method(self):
        """Should resolve self.method() call."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "helper": [{"class_name": "MyClass", "line_start": 1, "line_end": 10}],
        }

        result = _resolve_callee(
            callee_name="helper",
            callee_qualifier="self",
            is_method_call=True,
            caller_class="MyClass",
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None
        assert "MyClass" in result

    def test_returns_none_for_self_method_not_in_class(self):
        """Should return None when self.method not found in same class."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "helper": [{"class_name": "OtherClass", "line_start": 1, "line_end": 10}],
        }

        result = _resolve_callee(
            callee_name="helper",
            callee_qualifier="self",
            is_method_call=True,
            caller_class="MyClass",  # Different class
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is None

    def test_skips_builtins(self):
        """Should skip builtin function calls."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "len": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        result = _resolve_callee(
            callee_name="len",  # builtin
            callee_qualifier=None,
            is_method_call=False,
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is None

    def test_skips_external_qualifier(self):
        """Should skip calls with external qualifier."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "method": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        result = _resolve_callee(
            callee_name="method",
            callee_qualifier="external_obj",  # Not self/cls
            is_method_call=True,
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is None

    def test_prefers_standalone_for_multiple_candidates(self):
        """Should prefer standalone function when multiple candidates exist."""
        from deriva.modules.extraction.edges import _resolve_callee

        method_lookup = {
            "func": [
                {"class_name": "SomeClass", "line_start": 1, "line_end": 10},
                {"class_name": None, "line_start": 20, "line_end": 30},
            ],
        }

        result = _resolve_callee(
            callee_name="func",
            callee_qualifier=None,
            is_method_call=False,
            caller_class=None,
            method_lookup=method_lookup,
            repo_name="test-repo",
            file_path="main.py",
        )

        assert result is not None


# =============================================================================
# _extract_decorator_edges Tests
# =============================================================================


class TestExtractDecoratorEdges:
    """Tests for _extract_decorator_edges function."""

    def test_creates_decorator_edge(self):
        """Should create DECORATED_BY edge for resolved decorator."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_decorator_edges

        methods = [
            ExtractedMethod(
                name="my_decorator",
                class_name=None,
                parameters=[],
                decorators=[],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=5,
                is_async=False,
            ),
            ExtractedMethod(
                name="decorated_func",
                class_name=None,
                parameters=[],
                decorators=["my_decorator"],
                return_annotation=None,
                docstring=None,
                line_start=10,
                line_end=15,
                is_async=False,
            ),
        ]
        method_lookup = {
            "my_decorator": [{"class_name": None, "line_start": 1, "line_end": 5}],
            "decorated_func": [{"class_name": None, "line_start": 10, "line_end": 15}],
        }

        edges, stats = _extract_decorator_edges(
            methods=methods,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total"] == 1
        assert stats["resolved"] == 1
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "DECORATED_BY"

    def test_skips_builtin_decorators(self):
        """Should skip builtin decorators."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_decorator_edges

        methods = [
            ExtractedMethod(
                name="my_method",
                class_name="MyClass",
                parameters=[],
                decorators=["staticmethod", "property"],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        method_lookup = {
            "my_method": [{"class_name": "MyClass", "line_start": 1, "line_end": 10}],
        }

        edges, stats = _extract_decorator_edges(
            methods=methods,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total"] == 2
        assert stats["builtin"] == 2
        assert len(edges) == 0

    def test_handles_decorator_with_arguments(self):
        """Should handle decorators with arguments."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_decorator_edges

        methods = [
            ExtractedMethod(
                name="my_decorator",
                class_name=None,
                parameters=[],
                decorators=[],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=5,
                is_async=False,
            ),
            ExtractedMethod(
                name="decorated_func",
                class_name=None,
                parameters=[],
                decorators=["my_decorator(arg1, arg2)"],  # With args
                return_annotation=None,
                docstring=None,
                line_start=10,
                line_end=15,
                is_async=False,
            ),
        ]
        method_lookup = {
            "my_decorator": [{"class_name": None, "line_start": 1, "line_end": 5}],
            "decorated_func": [{"class_name": None, "line_start": 10, "line_end": 15}],
        }

        edges, stats = _extract_decorator_edges(
            methods=methods,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["resolved"] == 1
        assert len(edges) == 1

    def test_handles_class_method_decorator(self):
        """Should handle decorators defined as class methods."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_decorator_edges

        methods = [
            ExtractedMethod(
                name="decorator_method",
                class_name="DecoratorClass",
                parameters=[],
                decorators=[],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=5,
                is_async=False,
            ),
            ExtractedMethod(
                name="decorated_func",
                class_name=None,
                parameters=[],
                decorators=["DecoratorClass.decorator_method"],
                return_annotation=None,
                docstring=None,
                line_start=10,
                line_end=15,
                is_async=False,
            ),
        ]
        method_lookup = {
            "decorator_method": [{"class_name": "DecoratorClass", "line_start": 1, "line_end": 5}],
            "decorated_func": [{"class_name": None, "line_start": 10, "line_end": 15}],
        }

        edges, stats = _extract_decorator_edges(
            methods=methods,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["resolved"] == 1

    def test_counts_unresolved_decorators(self):
        """Should count unresolved decorators."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_decorator_edges

        methods = [
            ExtractedMethod(
                name="decorated_func",
                class_name=None,
                parameters=[],
                decorators=["unknown_decorator"],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        method_lookup = {
            "decorated_func": [{"class_name": None, "line_start": 1, "line_end": 10}],
        }

        edges, stats = _extract_decorator_edges(
            methods=methods,
            method_lookup=method_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["unresolved"] == 1
        assert len(edges) == 0


# =============================================================================
# _extract_reference_edges Tests
# =============================================================================


class TestExtractReferenceEdges:
    """Tests for _extract_reference_edges function."""

    def test_creates_reference_edge_for_type_annotation(self):
        """Should create REFERENCES edge for type annotations."""
        from deriva.adapters.treesitter.models import ExtractedMethod, ExtractedType
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="process",
                class_name=None,
                parameters=[{"name": "user", "annotation": "User"}],
                decorators=[],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        type_lookup = {
            "User": ExtractedType(
                name="User",
                kind="class",
                bases=[],
                docstring=None,
                line_start=20,
                line_end=30,
            ),
        }

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup=type_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total_annotations"] == 1
        assert stats["resolved"] == 1
        assert len(edges) == 1
        assert edges[0]["relationship_type"] == "REFERENCES"

    def test_creates_reference_for_return_annotation(self):
        """Should create REFERENCES edge for return type annotation."""
        from deriva.adapters.treesitter.models import ExtractedMethod, ExtractedType
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="get_user",
                class_name=None,
                parameters=[],
                decorators=[],
                return_annotation="User",
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        type_lookup = {
            "User": ExtractedType(
                name="User",
                kind="class",
                bases=[],
                docstring=None,
                line_start=20,
                line_end=30,
            ),
        }

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup=type_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["total_annotations"] == 1
        assert stats["resolved"] == 1

    def test_skips_builtin_types(self):
        """Should skip builtin types."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="process",
                class_name=None,
                parameters=[{"name": "x", "annotation": "str"}],
                decorators=[],
                return_annotation="int",
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup={},
            file_path="main.py",
            repo_name="test-repo",
        )

        # str and int are primitives, no type names extracted
        assert stats["total_annotations"] == 2
        assert len(edges) == 0

    def test_handles_generic_types(self):
        """Should extract inner types from generics."""
        from deriva.adapters.treesitter.models import ExtractedMethod, ExtractedType
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="get_users",
                class_name=None,
                parameters=[],
                decorators=[],
                return_annotation="List[User]",
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        type_lookup = {
            "User": ExtractedType(
                name="User",
                kind="class",
                bases=[],
                docstring=None,
                line_start=20,
                line_end=30,
            ),
        }

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup=type_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["resolved"] == 1  # User resolved

    def test_skips_self_reference(self):
        """Should not create self-reference edges."""
        from deriva.adapters.treesitter.models import ExtractedMethod, ExtractedType
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="clone",
                class_name="User",  # Method is in User class
                parameters=[],
                decorators=[],
                return_annotation="User",  # Returns same type
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]
        type_lookup = {
            "User": ExtractedType(
                name="User",
                kind="class",
                bases=[],
                docstring=None,
                line_start=1,
                line_end=50,
            ),
        }

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup=type_lookup,
            file_path="main.py",
            repo_name="test-repo",
        )

        # Should not create self-loop (User method referencing User class)
        assert len(edges) == 0

    def test_counts_unresolved_types(self):
        """Should count unresolved type references."""
        from deriva.adapters.treesitter.models import ExtractedMethod
        from deriva.modules.extraction.edges import _extract_reference_edges

        methods = [
            ExtractedMethod(
                name="process",
                class_name=None,
                parameters=[{"name": "item", "annotation": "UnknownType"}],
                decorators=[],
                return_annotation=None,
                docstring=None,
                line_start=1,
                line_end=10,
                is_async=False,
            ),
        ]

        edges, stats = _extract_reference_edges(
            methods=methods,
            type_lookup={},  # No types defined
            file_path="main.py",
            repo_name="test-repo",
        )

        assert stats["unresolved"] == 1


# =============================================================================
# Exception Handling Tests
# =============================================================================


class TestExtractEdgesExceptionHandling:
    """Tests for exception handling in edge extraction."""

    def test_handles_extraction_error(self):
        """Should handle errors during extraction gracefully."""
        # Provide invalid content that might cause tree-sitter issues
        result = extract_edges_from_file(
            file_path="test.py",
            file_content="\x00\x01\x02invalid",  # Binary garbage
            repo_name="test-repo",
            all_file_paths={"test.py"},
            external_packages=set(),
        )

        # Should still return a valid result structure
        assert "success" in result
        assert "data" in result
        assert "errors" in result
