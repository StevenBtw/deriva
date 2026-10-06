"""
Classification Module - Pure Functions for File Type Classification

This module provides simple, lightweight functions for classifying files
in repositories based on file extensions, patterns, and paths.

Classification priority order:
0. Excluded extensions (file type 'exclude', any length, e.g. '.archimate'): never an input, wherever the file lives
1. Path patterns (e.g., 'path:**/tests/**' matches any file in tests directory)
2. Full filename match (e.g., 'requirements.txt', 'Makefile')
3. Wildcard pattern match (e.g., 'test_*.py', '*.config.js')
4. Extension match (e.g., '.py', '.md')

Path patterns use 'path:' prefix and support glob syntax:
- 'path:**/tests/**' - matches any file in any 'tests' directory
- 'path:docs/*' - matches files directly in 'docs' directory
- 'path:**/static/**' - matches any file in any 'static' directory
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any


def _match_path_pattern(file_path: str, pattern: str) -> bool:
    """
    Match a file path against a glob pattern.

    Supports ** patterns for recursive directory matching and normalizes
    path separators for cross-platform compatibility.

    IMPORTANT: Directory components are matched as whole path segments,
    not substrings. E.g., '**/tests/**' will NOT match '/contests/foo.py'.

    Args:
        file_path: File path to match (can use any separator)
        pattern: Glob pattern (uses forward slashes)

    Returns:
        True if path matches pattern

    Examples:
        >>> _match_path_pattern("src/tests/test_app.py", "**/tests/**")
        True
        >>> _match_path_pattern("src/app.py", "**/tests/**")
        False
        >>> _match_path_pattern("src/contests/app.py", "**/tests/**")
        False  # 'contests' is not 'tests'
        >>> _match_path_pattern("docs/readme.md", "docs/*")
        True
    """
    # Normalize path to forward slashes for consistent matching
    normalized_path = file_path.replace("\\", "/").lower()
    pattern = pattern.lower()

    # Handle ** patterns by checking if directory components match
    if "**" in pattern:
        # Extract the directory names between ** markers
        # Pattern: **/tests/** -> extract 'tests' as directory to match
        parts = [p.strip("/") for p in pattern.split("**") if p.strip("/")]

        for part in parts:
            # Match as a directory component, not a substring
            # Use regex to match: start of path or /, then part, then / or end
            dir_pattern = rf"(^|/){re.escape(part)}(/|$)"
            if not re.search(dir_pattern, normalized_path):
                return False
        return True
    else:
        return fnmatch.fnmatch(normalized_path, pattern)


def classify_files(file_paths: list[str], file_type_registry: list[dict[str, str]]) -> dict[str, Any]:
    """
    Classify files based on file type registry.

    Pure function that takes file paths and a registry, returns classification results.

    Classification priority order:
    1. Path patterns (prefix 'path:') - based on file location
    2. Full filename match (e.g., 'requirements.txt', 'Makefile')
    3. Wildcard pattern match (e.g., 'test_*.py', '*.config.js')
    4. Extension match (e.g., '.py', '.md')

    Args:
        file_paths: List of file path strings (relative or absolute)
        file_type_registry: List of dicts with 'extension', 'file_type', and optionally 'subtype' keys
            Example: [{'extension': '.py', 'file_type': 'source', 'subtype': 'python'}, ...]
            Example: [{'extension': 'requirements.txt', 'file_type': 'dependency', 'subtype': 'python'}, ...]
            Example: [{'extension': 'test_*.py', 'file_type': 'test', 'subtype': 'python'}, ...]
            Example: [{'extension': 'path:**/tests/**', 'file_type': 'test', 'subtype': ''}, ...]

    Returns:
        Dict with:
            - classified: List[Dict] - Files with known types (includes file_type and subtype)
            - undefined: List[Dict] - Files with undefined types
            - stats: Dict - Classification statistics
            - errors: List[str] - Any error messages
    """
    classified = []
    undefined = []
    errors = []

    # Build four lookup structures:
    # 1. Path patterns (for entries like 'path:**/tests/**')
    # 2. Full filename map (for entries like 'requirements.txt', 'Makefile')
    # 3. Wildcard patterns list (for entries like 'test_*.py', '*.config.js')
    # 4. Extension map (for entries like '.py', '.md')
    path_patterns: list[tuple[str, dict[str, str]]] = []
    filename_map: dict[str, dict[str, str]] = {}
    wildcard_patterns: list[tuple[str, dict[str, str]]] = []
    extension_map: dict[str, dict[str, str]] = {}
    # Excluded file types by extension (any length): checked before the path patterns
    excluded_extensions: dict[str, dict[str, str]] = {}

    for entry in file_type_registry:
        if "extension" not in entry or "file_type" not in entry:
            continue

        key = entry["extension"].lower()
        type_info = {
            "file_type": entry["file_type"],
            "subtype": entry.get("subtype", ""),
        }

        if entry["file_type"] == "exclude" and key.startswith(".") and "." not in key[1:]:
            excluded_extensions[key] = type_info

        # Categorize by pattern type
        if key.startswith("path:"):
            # Path pattern (e.g., 'path:**/tests/**')
            path_patterns.append((key[5:], type_info))  # Strip 'path:' prefix
        elif "*" in key or "?" in key:
            # Wildcard pattern (e.g., 'test_*.py', '*.config.js')
            wildcard_patterns.append((key, type_info))
        elif key.startswith(".") and len(key) <= 5 and key[1:].isalpha():
            # Short alphabetic extension (e.g., '.py', '.md', '.html')
            extension_map[key] = type_info
        elif key.startswith("."):
            # Dotfile (e.g., '.flaskenv', '.gitignore', '.env')
            filename_map[key] = type_info
        else:
            # Full filename (e.g., 'requirements.txt', 'Makefile')
            filename_map[key] = type_info

    for file_path in file_paths:
        try:
            path = Path(file_path)
            filename = path.name.lower()
            extension = path.suffix.lower()

            # Priority 0: excluded file types are never an input, wherever they live
            if extension in excluded_extensions:
                type_info = excluded_extensions[extension]
                classified.append({"path": file_path, "extension": extension, "file_type": type_info["file_type"], "subtype": type_info["subtype"]})
                continue

            # Priority 1: Check path patterns (e.g., **/tests/**)
            matched_path = None
            for pattern, type_info in path_patterns:
                if _match_path_pattern(file_path, pattern):
                    matched_path = (pattern, type_info)
                    break

            if matched_path:
                pattern, type_info = matched_path
                classified.append(
                    {
                        "path": file_path,
                        "extension": f"path:{pattern}",
                        "file_type": type_info["file_type"],
                        "subtype": type_info["subtype"],
                    }
                )
                continue

            # Priority 2: Check full filename match (e.g., requirements.txt, Makefile)
            if filename in filename_map:
                type_info = filename_map[filename]
                classified.append(
                    {
                        "path": file_path,
                        "extension": filename,  # Use filename as the matched pattern
                        "file_type": type_info["file_type"],
                        "subtype": type_info["subtype"],
                    }
                )
                continue

            # Priority 3: Check wildcard pattern match (e.g., test_*.py)
            matched_pattern = None
            for pattern, type_info in wildcard_patterns:
                if fnmatch.fnmatch(filename, pattern):
                    matched_pattern = (pattern, type_info)
                    break

            if matched_pattern:
                pattern, type_info = matched_pattern
                classified.append(
                    {
                        "path": file_path,
                        "extension": pattern,  # Use pattern as the matched pattern
                        "file_type": type_info["file_type"],
                        "subtype": type_info["subtype"],
                    }
                )
                continue

            # Priority 4: Check extension match
            if not extension:
                # Files without extension (but not matched by filename or pattern)
                undefined.append({"path": file_path, "extension": "", "reason": "no_extension"})
                continue

            # A registered extension longer than four letters (.gradle, .properties) is kept with the
            # dotfile names; it still classifies a file by its suffix
            type_info = extension_map.get(extension) or filename_map.get(extension)
            if type_info:
                classified.append(
                    {
                        "path": file_path,
                        "extension": extension,
                        "file_type": type_info["file_type"],
                        "subtype": type_info["subtype"],
                    }
                )
            else:
                # Unknown file type
                undefined.append(
                    {
                        "path": file_path,
                        "extension": extension,
                        "reason": "unknown_extension",
                    }
                )

        except Exception as e:
            errors.append(f"Error processing {file_path}: {str(e)}")

    return {
        "classified": classified,
        "undefined": undefined,
        "stats": {
            "total_files": len(file_paths),
            "classified_count": len(classified),
            "undefined_count": len(undefined),
            "error_count": len(errors),
        },
        "errors": errors,
    }


def get_undefined_extensions(undefined_files: list[dict]) -> list[str]:
    """
    Extract unique undefined extensions from classification results.

    Pure function to get a list of extensions that need to be added to registry.

    Args:
        undefined_files: List of undefined file dicts from classify_files()

    Returns:
        List of unique extension strings (sorted, lowercase)
    """
    extensions = set()

    for file_info in undefined_files:
        if "extension" in file_info and file_info["extension"]:
            extensions.add(file_info["extension"].lower())

    return sorted(list(extensions))


def build_registry_update_list(undefined_extensions: list[str], default_type: str = "Undefined") -> list[dict[str, str]]:
    """
    Build a list of new registry entries for undefined extensions.

    Pure function that creates registry entries ready for database insertion.

    Args:
        undefined_extensions: List of extension strings (e.g., ['.jsx', '.ts'])
        default_type: Default file type to assign (default: "Undefined")

    Returns:
        List of dicts with 'extension' and 'file_type' keys
    """
    return [{"extension": ext, "file_type": default_type} for ext in undefined_extensions]
