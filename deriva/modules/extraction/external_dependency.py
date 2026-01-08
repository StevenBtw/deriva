"""
ExternalDependency extraction module.

This module extracts ExternalDependency nodes representing libraries, external APIs,
and external service integrations. It supports multiple extraction methods:

1. Deterministic parsing (requirements.txt, pyproject.toml, package.json)
2. AST-based extraction (Python imports)
3. LLM-based extraction (fallback for other files)

The extraction strategy is automatically chosen based on file type.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from deriva.common.json_utils import extract_json_from_response

from .base import (
    create_empty_llm_details,
    current_timestamp,
    generate_edge_id,
    strip_chunk_suffix,
)

# =============================================================================
# JSON Schema for LLM structured output
# =============================================================================

EXTERNAL_DEPENDENCY_SCHEMA = {
    "name": "external_dependency_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dependencyName": {
                            "type": "string",
                            "description": "Name of the dependency",
                        },
                        "dependencyCategory": {
                            "type": "string",
                            "enum": [
                                "library",
                                "external_api",
                                "external_service",
                                "external_database",
                            ],
                            "description": "Category of external dependency",
                        },
                        "version": {
                            "type": ["string", "null"],
                            "description": "Version constraint if applicable",
                        },
                        "ecosystem": {
                            "type": ["string", "null"],
                            "description": "Package ecosystem or provider",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this dependency is used for",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "dependencyName",
                        "dependencyCategory",
                        "version",
                        "ecosystem",
                        "description",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["dependencies"],
        "additionalProperties": False,
    },
}

# =============================================================================
# Standard library modules (for filtering AST imports)
# =============================================================================

PYTHON_STDLIB_MODULES = {
    "abc",
    "aifc",
    "argparse",
    "array",
    "ast",
    "asynchat",
    "asyncio",
    "asyncore",
    "atexit",
    "audioop",
    "base64",
    "bdb",
    "binascii",
    "binhex",
    "bisect",
    "builtins",
    "bz2",
    "calendar",
    "cgi",
    "cgitb",
    "chunk",
    "cmath",
    "cmd",
    "code",
    "codecs",
    "codeop",
    "collections",
    "colorsys",
    "compileall",
    "concurrent",
    "configparser",
    "contextlib",
    "contextvars",
    "copy",
    "copyreg",
    "cprofile",
    "crypt",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "distutils",
    "doctest",
    "email",
    "encodings",
    "enum",
    "errno",
    "faulthandler",
    "fcntl",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "graphlib",
    "grp",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "idlelib",
    "imaplib",
    "imghdr",
    "imp",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "lib2to3",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "mailcap",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "multiprocessing",
    "netrc",
    "nis",
    "nntplib",
    "numbers",
    "operator",
    "optparse",
    "os",
    "ossaudiodev",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posix",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "pwd",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "site",
    "smtpd",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "spwd",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symtable",
    "sys",
    "sysconfig",
    "syslog",
    "tabnanny",
    "tarfile",
    "telnetlib",
    "tempfile",
    "termios",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "tkinter",
    "token",
    "tokenize",
    "tomllib",
    "trace",
    "traceback",
    "tracemalloc",
    "tty",
    "turtle",
    "turtledemo",
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
    "winsound",
    "wsgiref",
    "xdrlib",
    "xml",
    "xmlrpc",
    "zipapp",
    "zipfile",
    "zipimport",
    "zlib",
    "__future__",
    "typing_extensions",
}


# =============================================================================
# Extraction Method Selection
# =============================================================================


def get_extraction_method(file_path: str, subtype: str | None) -> str:
    """
    Determine the best extraction method for a file.

    Args:
        file_path: Path to the file
        subtype: File subtype from classification

    Returns:
        One of: "requirements_txt", "pyproject_toml", "package_json",
                "python_ast", "llm"
    """
    filename = file_path.lower().split("/")[-1].split("\\")[-1]

    # Deterministic parsers for structured dependency files
    if filename == "requirements.txt" or filename.endswith("-requirements.txt"):
        return "requirements_txt"
    if filename == "pyproject.toml":
        return "pyproject_toml"
    if filename == "package.json":
        return "package_json"

    # AST extraction for Python source files
    if subtype and subtype.lower() == "python":
        return "python_ast"

    # LLM fallback for other files
    return "llm"


# =============================================================================
# Deterministic Extraction: requirements.txt
# =============================================================================


def _extract_from_requirements_txt(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """Extract dependencies from requirements.txt deterministically."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    original_path = strip_chunk_suffix(file_path)
    safe_path = original_path.replace("/", "_").replace("\\", "_")
    file_node_id = f"file_{repo_name}_{safe_path}"

    seen: set[str] = set()

    for line in file_content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        dep = _parse_requirement_line(line)
        if not dep:
            continue

        dep_name_lower = dep["name"].lower()
        if dep_name_lower in seen:
            continue
        seen.add(dep_name_lower)

        node, edge = _build_dependency_node_and_edge(
            name=dep["name"],
            version=dep.get("version"),
            ecosystem="pypi",
            origin_source=file_path,
            repo_name=repo_name,
            file_node_id=file_node_id,
            extraction_method="deterministic",
        )
        nodes.append(node)
        edges.append(edge)

    return _build_result(nodes, edges, [], "deterministic")


def _parse_requirement_line(line: str) -> dict[str, Any] | None:
    """Parse a single requirement line into package name and version."""
    line = line.strip()
    if not line:
        return None

    # Handle URL-based requirements (package @ url)
    if " @ " in line:
        name = line.split(" @ ")[0].strip()
        if "[" in name:
            name = name.split("[")[0]
        return {"name": name, "version": None}

    # Handle environment markers
    if ";" in line:
        line = line.split(";")[0].strip()

    # Extract package name
    match = re.match(r"^([a-zA-Z0-9][-a-zA-Z0-9._]*)(\[[^\]]+\])?(.*)", line)
    if not match:
        return None

    name = match.group(1)
    version_spec = match.group(3).strip() if match.group(3) else None

    version = None
    if version_spec:
        version_match = re.search(r"[0-9].*", version_spec)
        version = version_match.group(0) if version_match else version_spec

    return {"name": name, "version": version}


# =============================================================================
# Deterministic Extraction: pyproject.toml
# =============================================================================


def _extract_from_pyproject_toml(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """Extract dependencies from pyproject.toml deterministically."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    original_path = strip_chunk_suffix(file_path)
    safe_path = original_path.replace("/", "_").replace("\\", "_")
    file_node_id = f"file_{repo_name}_{safe_path}"

    seen: set[str] = set()

    # Simple TOML parsing for dependencies
    deps_pattern = r"dependencies\s*=\s*\[(.*?)\]"
    matches = re.findall(deps_pattern, file_content, re.DOTALL)

    for match in matches:
        dep_strings = re.findall(r'"([^"]+)"|\'([^\']+)\'', match)
        for dep_tuple in dep_strings:
            dep_str = dep_tuple[0] or dep_tuple[1]
            dep = _parse_requirement_line(dep_str)
            if not dep:
                continue

            dep_name_lower = dep["name"].lower()
            if dep_name_lower in seen:
                continue
            seen.add(dep_name_lower)

            node, edge = _build_dependency_node_and_edge(
                name=dep["name"],
                version=dep.get("version"),
                ecosystem="pypi",
                origin_source=file_path,
                repo_name=repo_name,
                file_node_id=file_node_id,
                extraction_method="deterministic",
            )
            nodes.append(node)
            edges.append(edge)

    return _build_result(nodes, edges, [], "deterministic")


# =============================================================================
# Deterministic Extraction: package.json
# =============================================================================


def _extract_from_package_json(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """Extract dependencies from package.json deterministically."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    errors: list[str] = []

    original_path = strip_chunk_suffix(file_path)
    safe_path = original_path.replace("/", "_").replace("\\", "_")
    file_node_id = f"file_{repo_name}_{safe_path}"

    seen: set[str] = set()

    try:
        data = json.loads(file_content)
    except json.JSONDecodeError as e:
        return _build_result([], [], [f"JSON parse error: {e}"], "deterministic")

    for dep_key in ["dependencies", "devDependencies"]:
        deps = data.get(dep_key, {})
        if not isinstance(deps, dict):
            continue

        for name, version in deps.items():
            name_lower = name.lower()
            if name_lower in seen:
                continue
            seen.add(name_lower)

            node, edge = _build_dependency_node_and_edge(
                name=name,
                version=version if isinstance(version, str) else None,
                ecosystem="npm",
                origin_source=file_path,
                repo_name=repo_name,
                file_node_id=file_node_id,
                extraction_method="deterministic",
            )
            nodes.append(node)
            edges.append(edge)

    return _build_result(nodes, edges, errors, "deterministic")


# =============================================================================
# AST-based Extraction: Python imports
# =============================================================================


def _extract_from_python_ast(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """Extract external dependencies from Python imports using AST."""
    from deriva.adapters.ast import ASTManager

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    errors: list[str] = []

    original_path = strip_chunk_suffix(file_path)
    safe_path = original_path.replace("/", "_").replace("\\", "_")
    file_node_id = f"file_{repo_name}_{safe_path}"

    seen: set[str] = set()

    try:
        ast_manager = ASTManager()
        imports = ast_manager.extract_imports(file_content, file_path)

        for imp in imports:
            module = imp.module.split(".")[0] if imp.module else ""
            if not module:
                continue

            # Skip standard library
            if module.lower() in PYTHON_STDLIB_MODULES:
                continue

            # Skip relative imports
            if imp.is_from_import and not imp.module:
                continue

            module_lower = module.lower()
            if module_lower in seen:
                continue
            seen.add(module_lower)

            node, edge = _build_dependency_node_and_edge(
                name=module,
                version=None,
                ecosystem="pypi",
                origin_source=file_path,
                repo_name=repo_name,
                file_node_id=file_node_id,
                extraction_method="ast",
            )
            nodes.append(node)
            edges.append(edge)

    except SyntaxError as e:
        errors.append(f"Python syntax error: {e}")
    except Exception as e:
        errors.append(f"AST extraction error: {e}")

    return _build_result(nodes, edges, errors, "ast")


# =============================================================================
# LLM-based Extraction (fallback)
# =============================================================================


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """Build the LLM prompt for external dependency extraction."""
    return f"""You are analyzing a file to extract external dependencies.

## Context
- **File Path:** {file_path}

## Instructions
{instruction}

## Example Output
{example}

## File Content
```
{file_content}
```

Extract external dependencies. Return ONLY a JSON object with a "dependencies" array. If no dependencies are found, return {{"dependencies": []}}.
"""


def _extract_from_llm(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn: Callable,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Extract external dependencies using LLM."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    errors: list[str] = []
    llm_details = create_empty_llm_details()

    try:
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_extraction_prompt(file_content, file_path, instruction, example)
        llm_details["prompt"] = prompt

        response = llm_query_fn(prompt, EXTERNAL_DEPENDENCY_SCHEMA)

        if hasattr(response, "content"):
            llm_details["response"] = response.content
        if hasattr(response, "usage") and response.usage:
            llm_details["tokens_in"] = response.usage.get("prompt_tokens", 0)
            llm_details["tokens_out"] = response.usage.get("completion_tokens", 0)
        if hasattr(response, "response_type"):
            llm_details["cache_used"] = (
                str(response.response_type) == "ResponseType.CACHED"
            )

        if hasattr(response, "error"):
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"LLM error: {response.error}"],
                "stats": {"total_nodes": 0, "total_edges": 0, "llm_error": True},
                "llm_details": llm_details,
            }

        parse_result = parse_llm_response(response.content)
        if not parse_result["success"]:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": parse_result["errors"],
                "stats": {"total_nodes": 0, "total_edges": 0, "parse_error": True},
                "llm_details": llm_details,
            }

        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        for dep_data in parse_result["data"]:
            node_result = build_external_dependency_node(dep_data, file_path, repo_name)
            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)
                edge = {
                    "edge_id": generate_edge_id(
                        file_node_id, node_data["node_id"], "USES"
                    ),
                    "from_node_id": file_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "USES",
                    "properties": {"created_at": current_timestamp()},
                }
                edges.append(edge)
            else:
                errors.extend(node_result["errors"])

        result = _build_result(nodes, edges, errors, "llm")
        result["llm_details"] = llm_details
        return result

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error: {e}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """Parse and validate LLM response content."""
    try:
        extracted = extract_json_from_response(response_content)
        parsed = json.loads(extracted)

        if parsed is None:
            return {"success": True, "data": [], "errors": []}
        if isinstance(parsed, list):
            return {"success": True, "data": parsed, "errors": []}
        if not isinstance(parsed, dict):
            return {"success": True, "data": [], "errors": []}

        if "dependencies" in parsed:
            data = parsed["dependencies"]
            if isinstance(data, list):
                return {"success": True, "data": data, "errors": []}
            return {"success": True, "data": [], "errors": []}

        for key in ["result", "results", "items", "externalDependencies"]:
            if key in parsed and isinstance(parsed[key], list):
                return {"success": True, "data": parsed[key], "errors": []}

        return {"success": True, "data": [], "errors": []}

    except json.JSONDecodeError as e:
        return {"success": False, "data": [], "errors": [f"JSON parsing error: {e}"]}


def build_external_dependency_node(
    dep_data: dict[str, Any], origin_source: str, repo_name: str
) -> dict[str, Any]:
    """Build an ExternalDependency graph node from extracted data."""
    errors = []

    for field in ["dependencyName", "dependencyCategory"]:
        if field not in dep_data or not dep_data[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {"success": False, "data": {}, "errors": errors, "stats": {}}

    valid_categories = [
        "library",
        "external_api",
        "external_service",
        "external_database",
    ]
    category = dep_data["dependencyCategory"].lower()
    if category not in valid_categories:
        category = "library"

    dep_name_slug = dep_data["dependencyName"].lower()
    dep_name_slug = dep_name_slug.replace(" ", "_").replace("-", "_").replace("/", "_")
    node_id = f"extdep_{repo_name}_{dep_name_slug}"

    node_data = {
        "node_id": node_id,
        "label": "ExternalDependency",
        "properties": {
            "dependencyName": dep_data["dependencyName"],
            "dependencyCategory": category,
            "version": dep_data.get("version"),
            "ecosystem": dep_data.get("ecosystem"),
            "description": dep_data.get("description", ""),
            "originSource": origin_source,
            "confidence": dep_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {"success": True, "data": node_data, "errors": [], "stats": {}}


# =============================================================================
# Helper Functions
# =============================================================================


def _build_dependency_node_and_edge(
    name: str,
    version: str | None,
    ecosystem: str,
    origin_source: str,
    repo_name: str,
    file_node_id: str,
    extraction_method: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a dependency node and its USES edge."""
    dep_name_slug = name.lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    node_id = f"extdep_{repo_name}_{dep_name_slug}"

    node = {
        "node_id": node_id,
        "label": "ExternalDependency",
        "properties": {
            "dependencyName": name,
            "dependencyCategory": "library",
            "version": version,
            "ecosystem": ecosystem,
            "description": f"{ecosystem.upper()} package {name}",
            "originSource": origin_source,
            "confidence": 1.0,
            "extracted_at": current_timestamp(),
            "extraction_method": extraction_method,
        },
    }

    edge = {
        "edge_id": generate_edge_id(file_node_id, node_id, "USES"),
        "from_node_id": file_node_id,
        "to_node_id": node_id,
        "relationship_type": "USES",
        "properties": {"created_at": current_timestamp()},
    }

    return node, edge


def _build_result(
    nodes: list[dict], edges: list[dict], errors: list[str], method: str
) -> dict[str, Any]:
    """Build a standard extraction result."""
    return {
        "success": len(errors) == 0 or len(nodes) > 0,
        "data": {"nodes": nodes, "edges": edges},
        "errors": errors,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": {"ExternalDependency": len(nodes)},
            "extraction_method": method,
        },
    }


# =============================================================================
# Main Entry Points
# =============================================================================


def extract_external_dependencies(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn: Callable | None = None,
    config: dict[str, Any] | None = None,
    subtype: str | None = None,
) -> dict[str, Any]:
    """
    Extract external dependencies from a file.

    Automatically selects the best extraction method:
    1. Deterministic for requirements.txt, pyproject.toml, package.json
    2. AST for Python source files
    3. LLM for other files (requires llm_query_fn)

    Args:
        file_path: Path to the file being analyzed
        file_content: Content of the file
        repo_name: Repository name
        llm_query_fn: Optional LLM query function for fallback
        config: Optional extraction config for LLM
        subtype: Optional file subtype for method selection

    Returns:
        Dictionary with success, data, errors, stats
    """
    method = get_extraction_method(file_path, subtype)

    if method == "requirements_txt":
        return _extract_from_requirements_txt(file_path, file_content, repo_name)
    elif method == "pyproject_toml":
        return _extract_from_pyproject_toml(file_path, file_content, repo_name)
    elif method == "package_json":
        return _extract_from_package_json(file_path, file_content, repo_name)
    elif method == "python_ast":
        return _extract_from_python_ast(file_path, file_content, repo_name)
    elif method == "llm" and llm_query_fn is not None:
        return _extract_from_llm(
            file_path, file_content, repo_name, llm_query_fn, config or {}
        )
    else:
        return _build_result([], [], ["No extraction method available"], "none")


def extract_external_dependencies_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn: Callable | None = None,
    config: dict[str, Any] | None = None,
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract external dependencies from multiple files.

    Args:
        files: List of dicts with 'path', 'content', and optionally 'subtype' keys
        repo_name: Repository name
        llm_query_fn: Optional LLM query function
        config: Optional extraction config
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        Aggregated results from all file extractions
    """
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_file_results: list[dict[str, Any]] = []
    files_processed = 0
    files_with_deps = 0

    seen_dependencies: set[str] = set()
    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]
        subtype = file_info.get("subtype")

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_external_dependencies(
            file_path=file_path,
            file_content=file_content,
            repo_name=repo_name,
            llm_query_fn=llm_query_fn,
            config=config,
            subtype=subtype,
        )

        files_processed += 1

        all_file_results.append(
            {
                "file_path": file_path,
                "success": result["success"],
                "dependencies_extracted": len(result["data"]["nodes"]),
                "extraction_method": result["stats"].get(
                    "extraction_method", "unknown"
                ),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_deps += 1
            result_edges = result["data"].get("edges", [])
            for idx, node in enumerate(result["data"]["nodes"]):
                dep_name = node["properties"]["dependencyName"].lower()
                if dep_name not in seen_dependencies:
                    seen_dependencies.add(dep_name)
                    all_nodes.append(node)
                if idx < len(result_edges):
                    all_edges.append(result_edges[idx])

        if result["errors"]:
            all_errors.extend([f"{file_path}: {e}" for e in result["errors"]])

    return {
        "success": len(all_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": all_nodes, "edges": all_edges},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_types": {"ExternalDependency": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_dependencies": files_with_deps,
        },
        "file_results": all_file_results,
    }
