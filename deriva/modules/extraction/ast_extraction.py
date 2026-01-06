"""
AST-based extraction for Python files.

This module provides deterministic extraction of TypeDefinition and Method nodes
from Python source files using the AST adapter. It produces the same output format
as LLM-based extraction modules.

Use AST extraction for Python files to get:
- Precise line numbers (exact, not approximate)
- Deterministic results (same input = same output)
- Faster extraction (no LLM API calls)
- Accurate parameter types and return types

The output can optionally be enriched with LLM to add descriptions.
"""

from __future__ import annotations

from typing import Any

from deriva.adapters.ast import ASTManager, ExtractedMethod, ExtractedType

from .base import current_timestamp, generate_edge_id, strip_chunk_suffix


def extract_types_from_python(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """
    Extract TypeDefinition nodes from Python source using AST.

    Args:
        file_path: Path to the file being analyzed (relative to repo)
        file_content: Python source code
        repo_name: Repository name

    Returns:
        Dictionary with success, data, errors, stats (same format as LLM extraction)
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        ast_manager = ASTManager()
        extracted_types = ast_manager.extract_types(file_content, file_path)

        # Build file node ID for CONTAINS edges
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        for ext_type in extracted_types:
            node_data = _build_type_node_from_ast(ext_type, file_path, file_content, repo_name)
            nodes.append(node_data)

            # Create CONTAINS edge: File -> TypeDefinition
            edge = {
                "edge_id": generate_edge_id(file_node_id, node_data["node_id"], "CONTAINS"),
                "from_node_id": file_node_id,
                "to_node_id": node_data["node_id"],
                "relationship_type": "CONTAINS",
                "properties": {"created_at": current_timestamp()},
            }
            edges.append(edge)

        return {
            "success": True,
            "data": {"nodes": nodes, "edges": edges},
            "errors": [],
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"TypeDefinition": len(nodes)},
                "extraction_method": "ast",
            },
        }

    except SyntaxError as e:
        errors.append(f"Python syntax error in {file_path}: {e}")
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": errors,
            "stats": {"total_nodes": 0, "total_edges": 0, "extraction_method": "ast"},
        }
    except Exception as e:
        errors.append(f"AST extraction error in {file_path}: {e}")
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": errors,
            "stats": {"total_nodes": 0, "total_edges": 0, "extraction_method": "ast"},
        }


def extract_methods_from_python(
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """
    Extract Method nodes from Python source using AST.

    Args:
        file_path: Path to the file being analyzed (relative to repo)
        file_content: Python source code
        repo_name: Repository name

    Returns:
        Dictionary with success, data, errors, stats (same format as LLM extraction)
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        ast_manager = ASTManager()
        extracted_methods = ast_manager.extract_methods(file_content, file_path)

        # Build file node ID for CONTAINS edges
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        for ext_method in extracted_methods:
            node_data = _build_method_node_from_ast(ext_method, file_path, repo_name)
            nodes.append(node_data)

            # Create edge based on whether method belongs to a class or is top-level
            if ext_method.class_name:
                # Method belongs to class - edge from TypeDefinition to Method
                type_name_slug = ext_method.class_name.replace(" ", "_").replace("-", "_")
                type_node_id = f"typedef_{repo_name}_{safe_path}_{type_name_slug}"
                edge = {
                    "edge_id": generate_edge_id(type_node_id, node_data["node_id"], "CONTAINS"),
                    "from_node_id": type_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "CONTAINS",
                    "properties": {"created_at": current_timestamp()},
                }
            else:
                # Top-level function - edge from File to Method
                edge = {
                    "edge_id": generate_edge_id(file_node_id, node_data["node_id"], "CONTAINS"),
                    "from_node_id": file_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "CONTAINS",
                    "properties": {"created_at": current_timestamp()},
                }
            edges.append(edge)

        return {
            "success": True,
            "data": {"nodes": nodes, "edges": edges},
            "errors": [],
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"Method": len(nodes)},
                "extraction_method": "ast",
            },
        }

    except SyntaxError as e:
        errors.append(f"Python syntax error in {file_path}: {e}")
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": errors,
            "stats": {"total_nodes": 0, "total_edges": 0, "extraction_method": "ast"},
        }
    except Exception as e:
        errors.append(f"AST extraction error in {file_path}: {e}")
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": errors,
            "stats": {"total_nodes": 0, "total_edges": 0, "extraction_method": "ast"},
        }


def _build_type_node_from_ast(
    ext_type: ExtractedType,
    file_path: str,
    file_content: str,
    repo_name: str,
) -> dict[str, Any]:
    """Build a TypeDefinition node from AST extracted type."""
    # Map AST kind to extraction category
    category_map = {
        "class": "class",
        "function": "function",
        "type_alias": "alias",
    }
    category = category_map.get(ext_type.kind, "other")

    # Extract code snippet
    lines = file_content.split("\n")
    code_snippet = "\n".join(lines[ext_type.line_start - 1 : ext_type.line_end])

    # Generate node ID
    type_name_slug = ext_type.name.replace(" ", "_").replace("-", "_")
    file_path_slug = file_path.replace("/", "_").replace("\\", "_")
    node_id = f"typedef_{repo_name}_{file_path_slug}_{type_name_slug}"

    return {
        "node_id": node_id,
        "label": "TypeDefinition",
        "properties": {
            "typeName": ext_type.name,
            "category": category,
            "description": ext_type.docstring or f"{category.title()} {ext_type.name}",
            "interfaceType": None,  # AST can't determine this semantically
            "filePath": file_path,
            "startLine": ext_type.line_start,
            "endLine": ext_type.line_end,
            "codeSnippet": code_snippet,
            "confidence": 1.0,  # AST is deterministic
            "extracted_at": current_timestamp(),
            "extraction_method": "ast",
            # AST-specific properties
            "bases": ext_type.bases,
            "decorators": ext_type.decorators,
            "is_async": ext_type.is_async,
        },
    }


def _build_method_node_from_ast(
    ext_method: ExtractedMethod,
    file_path: str,
    repo_name: str,
) -> dict[str, Any]:
    """Build a Method node from AST extracted method."""
    # Determine visibility from Python conventions
    if ext_method.name.startswith("__") and not ext_method.name.endswith("__"):
        visibility = "protected"
    elif ext_method.name.startswith("_"):
        visibility = "private"
    else:
        visibility = "public"

    # Format parameters as string
    param_strs = []
    for param in ext_method.parameters:
        p_str = param["name"]
        if param.get("annotation"):
            p_str += f": {param['annotation']}"
        param_strs.append(p_str)
    parameters = ", ".join(param_strs)

    # Generate node ID
    method_name_slug = ext_method.name.replace(" ", "_").replace("-", "_")
    type_name_slug = (ext_method.class_name or "module").replace(" ", "_").replace("-", "_")
    file_path_slug = file_path.replace("/", "_").replace("\\", "_")
    node_id = f"method_{repo_name}_{file_path_slug}_{type_name_slug}_{method_name_slug}"

    return {
        "node_id": node_id,
        "label": "Method",
        "properties": {
            "methodName": ext_method.name,
            "returnType": ext_method.return_annotation or "None",
            "visibility": visibility,
            "parameters": parameters,
            "description": ext_method.docstring or f"Method {ext_method.name}",
            "isStatic": ext_method.is_static,
            "isAsync": ext_method.is_async,
            "typeName": ext_method.class_name or "",
            "filePath": file_path,
            "startLine": ext_method.line_start,
            "endLine": ext_method.line_end,
            "confidence": 1.0,  # AST is deterministic
            "extracted_at": current_timestamp(),
            "extraction_method": "ast",
            # AST-specific properties
            "decorators": ext_method.decorators,
            "is_classmethod": ext_method.is_classmethod,
            "is_property": ext_method.is_property,
        },
    }


def is_python_file(subtype: str | None) -> bool:
    """Check if a file is a Python file based on its subtype."""
    return subtype is not None and subtype.lower() == "python"


__all__ = [
    "extract_types_from_python",
    "extract_methods_from_python",
    "is_python_file",
]
