"""
Unified edge extraction - Build relationship edges from source code using Tree-sitter.

This module extracts all edge types from source files in a single AST parse:
- IMPORTS: File → File (internal imports)
- USES: File → ExternalDependency (external package imports)
- CALLS: Method → Method (function/method calls)
- DECORATED_BY: Method → Method (decorator relationships)
- REFERENCES: Method → TypeDefinition (type annotation references)

Efficiency: By parsing each file once and extracting all edge types together,
this module is 4x more efficient than running separate extraction passes.

Usage:
    from deriva.modules.extraction.edges import extract_edges_batch, EdgeType

    # Extract all edge types (default)
    result = extract_edges_batch(files, repo_name, repo_path)

    # Extract specific edge types only
    result = extract_edges_batch(
        files, repo_name, repo_path,
        edge_types={EdgeType.IMPORTS, EdgeType.CALLS}
    )
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.models import (
    ExtractedCall,
    ExtractedImport,
    ExtractedMethod,
    ExtractedType,
    FilterConstants,
)

from .base import (
    current_timestamp,
    generate_edge_id,
    generate_file_node_id,
    generate_method_node_id,
)

# =============================================================================
# Edge Types
# =============================================================================


class EdgeType(str, Enum):
    """Types of edges that can be extracted from source code."""

    IMPORTS = "IMPORTS"  # File → File (internal imports)
    USES = "USES"  # File → ExternalDependency (external imports)
    CALLS = "CALLS"  # Method → Method (function calls)
    DECORATED_BY = "DECORATED_BY"  # Method → Method (decorators)
    REFERENCES = "REFERENCES"  # Method → TypeDefinition (type annotations)


# Default: extract all edge types
ALL_EDGE_TYPES = set(EdgeType)

# Supported languages for tree-sitter extraction
SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "java", "csharp")


# =============================================================================
# Consolidated Constants
# =============================================================================

# Python stdlib modules (from imports.py)
PYTHON_STDLIB = {
    "abc",
    "argparse",
    "ast",
    "asyncio",
    "atexit",
    "base64",
    "bisect",
    "builtins",
    "calendar",
    "cgi",
    "cmd",
    "codecs",
    "collections",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "csv",
    "ctypes",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "dis",
    "email",
    "encodings",
    "enum",
    "errno",
    "faulthandler",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "glob",
    "graphlib",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "imaplib",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "multiprocessing",
    "netrc",
    "numbers",
    "operator",
    "optparse",
    "os",
    "pathlib",
    "pdb",
    "pickle",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "smtplib",
    "socket",
    "socketserver",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "sys",
    "sysconfig",
    "syslog",
    "tarfile",
    "tempfile",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "token",
    "tokenize",
    "trace",
    "traceback",
    "tracemalloc",
    "turtle",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "wsgiref",
    "xml",
    "xmlrpc",
    "zipfile",
    "zipimport",
    "zlib",
    "typing_extensions",
    "TYPE_CHECKING",
}

# Python builtins to skip in call resolution (from calls.py)
PYTHON_BUILTINS = {
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "breakpoint",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "compile",
    "complex",
    "delattr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "exec",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "memoryview",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
    # Common exceptions
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "AttributeError",
    "ImportError",
    "OSError",
    "IOError",
}

# Python builtin decorators to skip (from decorators.py)
PYTHON_DECORATOR_BUILTINS = {
    # Standard library
    "staticmethod",
    "classmethod",
    "property",
    "abstractmethod",
    "abstractproperty",
    "abstractclassmethod",
    "abstractstaticmethod",
    "dataclass",
    "dataclasses.dataclass",
    "functools.wraps",
    "functools.lru_cache",
    "functools.cache",
    "functools.cached_property",
    "functools.total_ordering",
    "functools.singledispatch",
    "functools.singledispatchmethod",
    "contextlib.contextmanager",
    "contextlib.asynccontextmanager",
    "typing.overload",
    "typing.override",
    "typing.final",
    "typing.no_type_check",
    "typing.runtime_checkable",
    # Common frameworks (usually external, not in file)
    "app.route",
    "app.get",
    "app.post",
    "app.put",
    "app.delete",
    "app.patch",
    "pytest.fixture",
    "pytest.mark",
    "pytest.mark.parametrize",
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.mark.xfail",
    "unittest.skip",
    "unittest.skipIf",
    "unittest.expectedFailure",
    "mock.patch",
    "unittest.mock.patch",
}

# Python builtin types to skip in reference resolution (from references.py)
PYTHON_BUILTIN_TYPES = {
    # Primitives
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "None",
    "complex",
    "object",
    # Collections (builtin)
    "list",
    "dict",
    "set",
    "tuple",
    "frozenset",
    # Typing module basics
    "Any",
    "Union",
    "Optional",
    "Callable",
    "Type",
    "ClassVar",
    "Final",
    "Literal",
    "TypeVar",
    "Generic",
    "Protocol",
    "Annotated",
    "Self",
    "Never",
    "NoReturn",
    # Collection types from typing
    "List",
    "Dict",
    "Set",
    "Tuple",
    "FrozenSet",
    "Sequence",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Iterable",
    "Iterator",
    "Generator",
    "Coroutine",
    "AsyncGenerator",
    "AsyncIterator",
    "AsyncIterable",
    "Awaitable",
    "ContextManager",
    "AsyncContextManager",
    "Pattern",
    "Match",
    # Common ABCs
    "ABC",
    "ABCMeta",
}

# Generic containers (we want the inner type, not the container)
GENERIC_CONTAINERS = {
    "List",
    "Dict",
    "Set",
    "Tuple",
    "FrozenSet",
    "Optional",
    "Union",
    "Sequence",
    "Mapping",
    "Iterable",
    "Iterator",
    "Generator",
    "Callable",
    "Type",
    "ClassVar",
    "Final",
    "Annotated",
    "Awaitable",
    "Coroutine",
    "AsyncGenerator",
}


# =============================================================================
# Main Extraction Functions
# =============================================================================


def extract_edges_from_file(
    file_path: str,
    file_content: str,
    repo_name: str,
    all_file_paths: set[str] | None = None,
    external_packages: set[str] | None = None,
    edge_types: set[EdgeType] | None = None,
    ts_manager: TreeSitterManager | None = None,
    global_method_lookup: dict[tuple[str, str | None], list[dict]] | None = None,
    global_type_lookup: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """
    Extract edges from a single source file using a single AST parse.

    Args:
        file_path: Relative path to the file within the repo
        file_content: The file content as a string
        repo_name: Repository name for node ID generation
        all_file_paths: Set of all file paths in the repo (for internal import resolution)
        external_packages: Set of known external package names
        edge_types: Which edge types to extract (default: all)
        ts_manager: Optional TreeSitterManager instance to reuse

    Returns:
        Dictionary with:
            - success: bool
            - data: Dict with 'edges' and 'nodes' lists
            - errors: List[str]
            - stats: Dict with extraction statistics per edge type
    """
    edges: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    errors: list[str] = []
    stats: dict[str, Any] = {
        "imports": {"internal": 0, "external": 0, "unresolved": 0},
        "calls": {"total": 0, "resolved": 0, "unresolved": 0},
        "decorators": {"total": 0, "resolved": 0, "builtin": 0, "unresolved": 0},
        "references": {
            "total_annotations": 0,
            "resolved": 0,
            "builtin": 0,
            "unresolved": 0,
        },
    }

    edge_types = edge_types or ALL_EDGE_TYPES
    all_file_paths = all_file_paths or set()
    external_packages = external_packages or set()

    try:
        # Use provided manager or create new one
        manager = ts_manager or TreeSitterManager()

        # Single parse: extract all data at once
        all_data = manager.extract_all(file_content, file_path)

        types: list[ExtractedType] = all_data["types"]
        methods: list[ExtractedMethod] = all_data["methods"]
        imports: list[ExtractedImport] = all_data["imports"]
        calls: list[ExtractedCall] = all_data["calls"]

        # Get language-specific filter constants
        filter_constants = manager.get_filter_constants(file_path=file_path)

        # Build lookups once (shared across edge types)
        type_lookup = {t.name: t for t in types}
        method_lookup = _build_method_lookup(methods)

        # Extract IMPORTS and USES edges (also creates ExternalDependency nodes)
        if EdgeType.IMPORTS in edge_types or EdgeType.USES in edge_types:
            import_edges, import_nodes, import_stats = _extract_import_edges(
                imports=imports,
                file_path=file_path,
                repo_name=repo_name,
                all_file_paths=all_file_paths,
                external_packages=external_packages,
                edge_types=edge_types,
                filter_constants=filter_constants,
            )
            edges.extend(import_edges)
            nodes.extend(import_nodes)
            stats["imports"] = import_stats

        # Extract CALLS edges
        if EdgeType.CALLS in edge_types:
            call_edges, call_stats = _extract_call_edges(
                calls=calls,
                method_lookup=method_lookup,
                file_path=file_path,
                repo_name=repo_name,
                filter_constants=filter_constants,
                global_method_lookup=global_method_lookup,
            )
            edges.extend(call_edges)
            stats["calls"] = call_stats

        # Extract DECORATED_BY edges
        if EdgeType.DECORATED_BY in edge_types:
            decorator_edges, decorator_stats = _extract_decorator_edges(
                methods=methods,
                method_lookup=method_lookup,
                file_path=file_path,
                repo_name=repo_name,
                filter_constants=filter_constants,
                global_method_lookup=global_method_lookup,
            )
            edges.extend(decorator_edges)
            stats["decorators"] = decorator_stats

        # Extract REFERENCES edges
        if EdgeType.REFERENCES in edge_types:
            reference_edges, reference_stats = _extract_reference_edges(
                methods=methods,
                type_lookup=type_lookup,
                file_path=file_path,
                repo_name=repo_name,
                filter_constants=filter_constants,
                global_type_lookup=global_type_lookup,
            )
            edges.extend(reference_edges)
            stats["references"] = reference_stats

    except Exception as e:
        errors.append(f"Failed to extract edges from {file_path}: {e!s}")

    return {
        "success": len(errors) == 0,
        "data": {"edges": edges, "nodes": nodes},
        "errors": errors,
        "stats": stats,
    }


def extract_edges_batch(
    files: list[dict[str, Any]],
    repo_name: str,
    repo_path: str | Path,
    edge_types: set[EdgeType] | None = None,
    external_packages: set[str] | None = None,
    progress_callback: Any | None = None,
    global_method_lookup: dict[tuple[str, str | None], list[dict]] | None = None,
    global_type_lookup: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """
    Extract edges from multiple source files efficiently.

    Uses a single TreeSitterManager instance and parses each file only once,
    extracting all requested edge types in a single pass.

    Args:
        files: List of file info dicts with 'path' and optionally 'content'
        repo_name: Repository name
        repo_path: Path to the repository root
        edge_types: Which edge types to extract (default: all)
        external_packages: Set of known external package names
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        Aggregated results with all edges, nodes, and statistics
    """
    all_edges: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()  # For deduplication
    all_errors: list[str] = []
    # Define nested stats dicts explicitly for type checker
    imports_stats: dict[str, int] = {"internal": 0, "external": 0, "unresolved": 0}
    calls_stats: dict[str, int] = {"total": 0, "resolved": 0, "unresolved": 0}
    decorators_stats: dict[str, int] = {
        "total": 0,
        "resolved": 0,
        "builtin": 0,
        "unresolved": 0,
    }
    references_stats: dict[str, int] = {
        "total_annotations": 0,
        "resolved": 0,
        "builtin": 0,
        "unresolved": 0,
    }
    files_processed = 0

    repo_path = Path(repo_path)
    edge_types = edge_types or ALL_EDGE_TYPES
    external_packages = external_packages or set()

    # Build set of all file paths for internal import resolution
    all_file_paths = {f["path"] for f in files}

    # Filter to only source files that Tree-sitter can parse
    source_files = [
        f
        for f in files
        if f.get("file_type") == "source" and f.get("subtype") in SUPPORTED_LANGUAGES
    ]

    total = len(source_files)

    # Reuse single TreeSitterManager instance for all files
    ts_manager = TreeSitterManager()

    for i, file_info in enumerate(source_files):
        file_path = file_info["path"]

        if progress_callback:
            progress_callback(i + 1, total, file_path)

        # Read file content if not provided
        content = file_info.get("content")
        if content is None:
            try:
                full_path = repo_path / file_path
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                all_errors.append(f"Failed to read {file_path}: {e}")
                continue

        # Extract all edge types from this file in one pass
        result = extract_edges_from_file(
            file_path=file_path,
            file_content=content,
            repo_name=repo_name,
            all_file_paths=all_file_paths,
            external_packages=external_packages,
            edge_types=edge_types,
            ts_manager=ts_manager,
            global_method_lookup=global_method_lookup,
            global_type_lookup=global_type_lookup,
        )

        all_edges.extend(result["data"]["edges"])
        all_errors.extend(result["errors"])
        files_processed += 1

        # Collect unique nodes (deduplicate across files)
        for node in result["data"].get("nodes", []):
            node_id = node.get("node_id")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                all_nodes.append(node)

        # Aggregate stats from result
        result_stats = result["stats"]
        for subkey, value in result_stats.get("imports", {}).items():
            imports_stats[subkey] = imports_stats.get(subkey, 0) + value
        for subkey, value in result_stats.get("calls", {}).items():
            calls_stats[subkey] = calls_stats.get(subkey, 0) + value
        for subkey, value in result_stats.get("decorators", {}).items():
            decorators_stats[subkey] = decorators_stats.get(subkey, 0) + value
        for subkey, value in result_stats.get("references", {}).items():
            references_stats[subkey] = references_stats.get(subkey, 0) + value

    return {
        "success": True,
        "data": {"edges": all_edges, "nodes": all_nodes},
        "errors": all_errors,
        "stats": {
            "files_processed": files_processed,
            "total_edges": len(all_edges),
            "total_nodes": len(all_nodes),
            "imports": imports_stats,
            "calls": calls_stats,
            "decorators": decorators_stats,
            "references": references_stats,
        },
    }


# =============================================================================
# Import Edge Extraction
# =============================================================================


def _extract_import_edges(
    imports: list[ExtractedImport],
    file_path: str,
    repo_name: str,
    all_file_paths: set[str],
    external_packages: set[str],
    edge_types: set[EdgeType],
    filter_constants: FilterConstants | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Extract IMPORTS and USES edges from import statements.

    Also creates/updates ExternalDependency nodes for external imports.

    Returns:
        Tuple of (edges, nodes, stats)
    """
    edges: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    seen_packages: set[str] = set()  # Track packages to avoid duplicate nodes
    stats = {"internal": 0, "external": 0, "unresolved": 0}

    # Use language-specific stdlib or fall back to Python stdlib
    stdlib_modules = (
        filter_constants.stdlib_modules if filter_constants else PYTHON_STDLIB
    )

    source_file_id = generate_file_node_id(repo_name, file_path)

    for imp in imports:
        resolved = _resolve_import(
            module=imp.module,
            current_file=file_path,
            all_file_paths=all_file_paths,
            external_packages=external_packages,
            stdlib_modules=stdlib_modules,
        )

        if resolved["type"] == "internal" and EdgeType.IMPORTS in edge_types:
            target_file_id = generate_file_node_id(repo_name, resolved["target_path"])
            edge = {
                "edge_id": generate_edge_id(source_file_id, target_file_id, "IMPORTS"),
                "from_node_id": source_file_id,
                "to_node_id": target_file_id,
                "relationship_type": "IMPORTS",
                "properties": {
                    "module": imp.module,
                    "names": imp.names,
                    "line": imp.line,
                    "is_from_import": imp.is_from_import,
                    "created_at": current_timestamp(),
                },
            }
            edges.append(edge)
            stats["internal"] += 1

        elif resolved["type"] == "external" and EdgeType.USES in edge_types:
            package_name = resolved["package"]
            package_slug = package_name.lower().replace("-", "_").replace(".", "_")
            target_id = f"extdep::{repo_name}::{package_slug}"

            edge = {
                "edge_id": generate_edge_id(source_file_id, target_id, "USES"),
                "from_node_id": source_file_id,
                "to_node_id": target_id,
                "relationship_type": "USES",
                "properties": {
                    "module": imp.module,
                    "names": imp.names,
                    "line": imp.line,
                    "is_from_import": imp.is_from_import,
                    "created_at": current_timestamp(),
                },
            }
            edges.append(edge)
            stats["external"] += 1

            # Create ExternalDependency node if not already seen
            # Node will be merged with existing node if one was created by ExternalDependency step
            if package_slug not in seen_packages:
                seen_packages.add(package_slug)
                node = {
                    "node_id": target_id,
                    "label": "ExternalDependency",
                    "properties": {
                        "dependencyName": package_name,
                        "dependencyCategory": "library",
                        "ecosystem": _infer_ecosystem(file_path),
                        "originSource": file_path,
                        "confidence": 1.0,
                        "extracted_at": current_timestamp(),
                        "declared": False,  # Not from manifest (will be merged if manifest node exists)
                        "used": True,  # Actually imported in code
                    },
                }
                nodes.append(node)

        else:
            stats["unresolved"] += 1

    return edges, nodes, stats


def _infer_ecosystem(file_path: str) -> str:
    """Infer package ecosystem from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext in (".py", ".pyw", ".pyi"):
        return "pypi"
    elif ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
        return "npm"
    elif ext == ".java":
        return "maven"
    elif ext == ".cs":
        return "nuget"
    else:
        return "unknown"


def _resolve_import(
    module: str,
    current_file: str,
    all_file_paths: set[str],
    external_packages: set[str],
    stdlib_modules: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve an import to determine if it's internal or external."""
    # Use provided stdlib or fall back to Python stdlib
    stdlib = stdlib_modules if stdlib_modules else PYTHON_STDLIB

    # Handle relative imports
    if module.startswith("."):
        target_path = _resolve_relative_import(module, current_file, all_file_paths)
        if target_path:
            return {"type": "internal", "target_path": target_path}
        return {"type": "unknown", "reason": "relative_not_found"}

    # Check if it's a known external package
    top_level = module.split(".")[0]
    if top_level in external_packages:
        return {"type": "external", "package": top_level}

    # Check stdlib modules (language-specific)
    if top_level in stdlib:
        return {"type": "stdlib", "module": top_level}

    # Try to resolve as internal module
    target_path = _resolve_absolute_import(module, all_file_paths)
    if target_path:
        return {"type": "internal", "target_path": target_path}

    # Could be external package not in our list
    return {"type": "external", "package": top_level}


def _resolve_relative_import(
    module: str,
    current_file: str,
    all_file_paths: set[str],
) -> str | None:
    """Resolve a relative import (e.g., '.models', '..utils') to a file path."""
    # Use PurePosixPath to ensure consistent forward-slash handling across platforms
    from pathlib import PurePosixPath

    current_dir = str(PurePosixPath(current_file).parent)
    if current_dir == ".":
        current_dir = ""

    # Count leading dots
    dots = 0
    for char in module:
        if char == ".":
            dots += 1
        else:
            break

    # Go up directories for each additional dot beyond the first
    parts = current_dir.split("/") if current_dir else []
    if dots > 1:
        parts = parts[: -(dots - 1)] if len(parts) >= dots - 1 else []

    # Get the module name after the dots
    module_name = module[dots:]

    # Build potential file paths
    if module_name:
        module_parts = module_name.split(".")
        base_path = "/".join(parts + module_parts) if parts else "/".join(module_parts)
    else:
        base_path = "/".join(parts) if parts else ""

    # Try different file patterns
    candidates = [f"{base_path}.py", f"{base_path}/__init__.py"]

    for candidate in candidates:
        if candidate in all_file_paths:
            return candidate

    return None


def _resolve_absolute_import(
    module: str,
    all_file_paths: set[str],
) -> str | None:
    """Resolve an absolute import to a file path within the repository."""
    parts = module.split(".")

    candidates = [
        "/".join(parts) + ".py",
        "/".join(parts) + "/__init__.py",
        "/".join(parts[:-1]) + ".py" if len(parts) > 1 else None,
    ]

    for candidate in candidates:
        if candidate and candidate in all_file_paths:
            return candidate

    return None


# =============================================================================
# Call Edge Extraction
# =============================================================================


def _extract_call_edges(
    calls: list[ExtractedCall],
    method_lookup: dict[str, list[dict[str, Any]]],
    file_path: str,
    repo_name: str,
    filter_constants: FilterConstants | None = None,
    global_method_lookup: dict[tuple[str, str | None], list[dict]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract CALLS edges from function/method calls.

    Uses global_method_lookup for cross-file resolution when available.
    Falls back to within-file resolution if global lookup is not provided.
    """
    edges: list[dict[str, Any]] = []
    stats = {"total": 0, "resolved": 0, "unresolved": 0, "cross_file": 0}

    # Use language-specific builtins or fall back to Python builtins
    builtin_functions = (
        filter_constants.builtin_functions if filter_constants else PYTHON_BUILTINS
    )

    for call in calls:
        stats["total"] += 1

        # Try to resolve the caller (must be in current file)
        caller_id = _resolve_caller(
            call.caller_name,
            call.caller_class,
            method_lookup,
            repo_name,
            file_path,
        )
        if not caller_id:
            stats["unresolved"] += 1
            continue

        # Skip common builtins
        if call.callee_name in builtin_functions:
            stats["unresolved"] += 1
            continue

        # If there's a qualifier that's not 'self'/'cls', it's likely external
        if call.callee_qualifier and call.callee_qualifier not in ("self", "cls"):
            stats["unresolved"] += 1
            continue

        # Try to resolve callee using global lookup first (cross-file)
        callee_id = None
        is_cross_file = False

        if global_method_lookup:
            # For self.method() calls, look for method in same class across files
            if call.is_method_call and call.callee_qualifier in ("self", "cls"):
                key = (call.callee_name, call.caller_class)
                candidates = global_method_lookup.get(key, [])
                if candidates:
                    # Prefer same file, then any file
                    for c in candidates:
                        if c["file_path"] == file_path:
                            callee_id = c["node_id"]
                            break
                    if not callee_id and candidates:
                        callee_id = candidates[0]["node_id"]
                        is_cross_file = True
            else:
                # For regular function calls, look up by name
                # Try with None class first (module-level function)
                key = (call.callee_name, None)
                candidates = global_method_lookup.get(key, [])
                if candidates:
                    # Prefer same file
                    for c in candidates:
                        if c["file_path"] == file_path:
                            callee_id = c["node_id"]
                            break
                    if not callee_id and candidates:
                        callee_id = candidates[0]["node_id"]
                        is_cross_file = True

        # Fall back to within-file resolution
        if not callee_id:
            callee_id = _resolve_callee(
                call.callee_name,
                call.callee_qualifier,
                call.is_method_call,
                call.caller_class,
                method_lookup,
                repo_name,
                file_path,
                builtin_functions=builtin_functions,
            )

        if not callee_id:
            stats["unresolved"] += 1
            continue

        # Don't create self-loops
        if caller_id == callee_id:
            continue

        edge = {
            "edge_id": generate_edge_id(caller_id, callee_id, "CALLS"),
            "from_node_id": caller_id,
            "to_node_id": callee_id,
            "relationship_type": "CALLS",
            "properties": {
                "line": call.line,
                "is_method_call": call.is_method_call,
                "qualifier": call.callee_qualifier,
                "cross_file": is_cross_file,
                "created_at": current_timestamp(),
            },
        }
        edges.append(edge)
        stats["resolved"] += 1
        if is_cross_file:
            stats["cross_file"] += 1

    return edges, stats


def _build_method_lookup(
    methods: list[ExtractedMethod],
) -> dict[str, list[dict[str, Any]]]:
    """Build a lookup table of methods by name."""
    lookup: dict[str, list[dict[str, Any]]] = {}
    for m in methods:
        name = m.name
        if name not in lookup:
            lookup[name] = []
        lookup[name].append(
            {
                "class_name": m.class_name,
                "line_start": m.line_start,
                "line_end": m.line_end,
            }
        )
    return lookup


def _resolve_caller(
    caller_name: str,
    caller_class: str | None,
    method_lookup: dict[str, list[dict[str, Any]]],
    repo_name: str,
    file_path: str,
) -> str | None:
    """Resolve a caller function/method to a node ID."""
    if caller_name not in method_lookup:
        return None

    candidates = method_lookup[caller_name]

    if len(candidates) == 1:
        return generate_method_node_id(
            repo_name, file_path, caller_name, candidates[0]["class_name"]
        )

    if caller_class:
        for c in candidates:
            if c["class_name"] == caller_class:
                return generate_method_node_id(
                    repo_name, file_path, caller_name, caller_class
                )

    for c in candidates:
        if c["class_name"] is None:
            return generate_method_node_id(repo_name, file_path, caller_name, None)

    return None


def _resolve_callee(
    callee_name: str,
    callee_qualifier: str | None,
    is_method_call: bool,
    caller_class: str | None,
    method_lookup: dict[str, list[dict[str, Any]]],
    repo_name: str,
    file_path: str,
    builtin_functions: set[str] | None = None,
) -> str | None:
    """Resolve a callee function/method to a node ID."""
    # Use provided builtins or fall back to Python builtins
    builtins = builtin_functions if builtin_functions else PYTHON_BUILTINS

    # Skip common builtins and external calls
    if callee_name in builtins:
        return None

    # If there's a qualifier that's not 'self', it's likely external
    if callee_qualifier and callee_qualifier not in ("self", "cls"):
        return None

    if callee_name not in method_lookup:
        return None

    candidates = method_lookup[callee_name]

    # For self.method() calls, look for method in same class
    if is_method_call and callee_qualifier in ("self", "cls") and caller_class:
        for c in candidates:
            if c["class_name"] == caller_class:
                return generate_method_node_id(
                    repo_name, file_path, callee_name, caller_class
                )
        return None

    if len(candidates) == 1:
        return generate_method_node_id(
            repo_name, file_path, callee_name, candidates[0]["class_name"]
        )

    for c in candidates:
        if c["class_name"] is None:
            return generate_method_node_id(repo_name, file_path, callee_name, None)

    return None


# =============================================================================
# Decorator Edge Extraction
# =============================================================================


def _extract_decorator_edges(
    methods: list[ExtractedMethod],
    method_lookup: dict[str, list[dict[str, Any]]],  # noqa: ARG001 - kept for API
    file_path: str,
    repo_name: str,
    filter_constants: FilterConstants | None = None,
    global_method_lookup: dict[tuple[str, str | None], list[dict]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract DECORATED_BY edges from method decorators.

    Uses global_method_lookup for cross-file resolution when available.
    """
    edges: list[dict[str, Any]] = []
    stats = {"total": 0, "resolved": 0, "builtin": 0, "unresolved": 0, "cross_file": 0}

    # Use language-specific builtin decorators or fall back to Python
    builtin_decorators = (
        filter_constants.builtin_decorators
        if filter_constants
        else PYTHON_DECORATOR_BUILTINS
    )

    # Build local lookup for within-file decorators
    local_func_lookup = {m.name: m for m in methods if not m.class_name}
    for m in methods:
        if m.class_name:
            local_func_lookup[f"{m.class_name}.{m.name}"] = m

    for method in methods:
        if not method.decorators:
            continue

        decorated_id = generate_method_node_id(
            repo_name, file_path, method.name, method.class_name
        )

        for decorator in method.decorators:
            stats["total"] += 1

            # Parse decorator name (strip parentheses and arguments)
            dec_name = decorator.split("(")[0].strip()

            # Skip builtin decorators (language-specific)
            if dec_name in builtin_decorators:
                stats["builtin"] += 1
                continue

            decorator_id = None
            is_cross_file = False

            # Try global lookup first for cross-file resolution
            if global_method_lookup:
                # Decorators are usually module-level functions
                key = (dec_name, None)
                candidates = global_method_lookup.get(key, [])
                if candidates:
                    # Prefer same file
                    for c in candidates:
                        if c["file_path"] == file_path:
                            decorator_id = c["node_id"]
                            break
                    if not decorator_id and candidates:
                        decorator_id = candidates[0]["node_id"]
                        is_cross_file = True

            # Fall back to within-file resolution
            if not decorator_id:
                decorator_method = local_func_lookup.get(dec_name)
                if decorator_method:
                    decorator_id = generate_method_node_id(
                        repo_name, file_path, decorator_method.name, None
                    )

            if not decorator_id:
                stats["unresolved"] += 1
                continue

            # Don't create self-loops
            if decorated_id == decorator_id:
                continue

            edge = {
                "edge_id": generate_edge_id(decorated_id, decorator_id, "DECORATED_BY"),
                "from_node_id": decorated_id,
                "to_node_id": decorator_id,
                "relationship_type": "DECORATED_BY",
                "properties": {
                    "decorator_text": decorator,
                    "cross_file": is_cross_file,
                    "created_at": current_timestamp(),
                },
            }
            edges.append(edge)
            stats["resolved"] += 1
            if is_cross_file:
                stats["cross_file"] += 1

    return edges, stats


# =============================================================================
# Reference Edge Extraction
# =============================================================================


def _extract_reference_edges(
    methods: list[ExtractedMethod],
    type_lookup: dict[str, ExtractedType],
    file_path: str,
    repo_name: str,
    filter_constants: FilterConstants | None = None,
    global_type_lookup: dict[str, list[dict]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract REFERENCES edges from type annotations.

    Uses global_type_lookup for cross-file resolution when available.
    """
    edges: list[dict[str, Any]] = []
    stats = {
        "total_annotations": 0,
        "resolved": 0,
        "builtin": 0,
        "unresolved": 0,
        "cross_file": 0,
    }

    # Use language-specific builtin types or fall back to Python
    builtin_types = (
        filter_constants.builtin_types if filter_constants else PYTHON_BUILTIN_TYPES
    )
    generic_containers = (
        filter_constants.generic_containers if filter_constants else GENERIC_CONTAINERS
    )

    for method in methods:
        method_id = generate_method_node_id(
            repo_name, file_path, method.name, method.class_name
        )

        referenced_types: set[str] = set()

        # Extract type names from parameters
        for param in method.parameters:
            annotation = param.get("annotation")
            if annotation:
                stats["total_annotations"] += 1
                type_names = _extract_type_names(annotation, generic_containers)
                referenced_types.update(type_names)

        # Extract type names from return annotation
        if method.return_annotation:
            stats["total_annotations"] += 1
            type_names = _extract_type_names(
                method.return_annotation, generic_containers
            )
            referenced_types.update(type_names)

        # Create edges for each referenced type
        for type_name in referenced_types:
            # Skip builtin types (language-specific)
            if type_name in builtin_types:
                stats["builtin"] += 1
                continue

            # Don't create self-loops (method referencing its own class)
            if method.class_name == type_name:
                continue

            type_id = None
            is_cross_file = False

            # Try global lookup first for cross-file resolution
            if global_type_lookup and type_name in global_type_lookup:
                candidates = global_type_lookup[type_name]
                # Prefer same file
                for c in candidates:
                    if c["file_path"] == file_path:
                        type_id = c["node_id"]
                        break
                if not type_id and candidates:
                    type_id = candidates[0]["node_id"]
                    is_cross_file = True

            # Fall back to within-file resolution
            if not type_id and type_name in type_lookup:
                type_def = type_lookup[type_name]
                file_path_slug = file_path.replace("/", "_").replace("\\", "_")
                type_name_slug = type_def.name.replace(" ", "_").replace("-", "_")
                type_id = f"typedef::{repo_name}::{file_path_slug}::{type_name_slug}"

            if not type_id:
                stats["unresolved"] += 1
                continue

            edge = {
                "edge_id": generate_edge_id(method_id, type_id, "REFERENCES"),
                "from_node_id": method_id,
                "to_node_id": type_id,
                "relationship_type": "REFERENCES",
                "properties": {
                    "reference_type": "type_annotation",
                    "cross_file": is_cross_file,
                    "created_at": current_timestamp(),
                },
            }
            edges.append(edge)
            stats["resolved"] += 1
            if is_cross_file:
                stats["cross_file"] += 1

    return edges, stats


def _extract_type_names(
    annotation: str,
    generic_containers: set[str] | None = None,
) -> set[str]:
    """Extract type names from a type annotation string."""
    type_names: set[str] = set()

    # Use provided containers or fall back to Python containers
    containers = generic_containers if generic_containers else GENERIC_CONTAINERS

    # Remove quotes (forward references)
    annotation = annotation.replace('"', "").replace("'", "")

    # Extract CamelCase/PascalCase names (likely type names)
    tokens = re.findall(r"\b([A-Z][a-zA-Z0-9_]*)\b", annotation)

    for token in tokens:
        if token not in containers:
            type_names.add(token)

    return type_names


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "EdgeType",
    "ALL_EDGE_TYPES",
    "SUPPORTED_LANGUAGES",
    "extract_edges_from_file",
    "extract_edges_batch",
    "PYTHON_STDLIB",
    "PYTHON_BUILTINS",
    "PYTHON_DECORATOR_BUILTINS",
    "PYTHON_BUILTIN_TYPES",
    "GENERIC_CONTAINERS",
]
