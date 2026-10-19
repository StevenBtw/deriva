"""Extraction coverage: which files of a checkout reached the graph, which were read for types and methods, and
whether the result is complete.

Structure only: the inputs come from the checkout and the graph, nothing is asked of an LLM, and the report
changes no result. A run is incomplete when files did not reach the graph, could not be read, or when there are
source files and not one gave a type or method. Source extensions no step reads, and read extensions without a
type or method, are notes: shell scripts or a config file have none by nature.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from pathlib import PurePosixPath
from typing import Any

__all__ = ["coverage_report"]

NO_EXTENSION = "(no extension)"
# How many paths a reason names
EXAMPLES = 3


def _extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower() or NO_EXTENSION


def _most_common(values: list[Any]) -> Any:
    return Counter(values).most_common(1)[0][0] if values else None


def _files(count: int) -> str:
    return f"{count} file{'s' if count != 1 else ''}"


def _named(paths: list[str]) -> str:
    """'a.py' for one path, 'for example a.py, b.py, c.py' for more."""
    shown = ", ".join(paths[:EXAMPLES])
    return shown if len(paths) == 1 else f"for example {shown}"


def coverage_report(
    checkout_files: Collection[str],
    graph_files: Mapping[str, Mapping[str, str]],
    read_by_step: Mapping[str, str],
    symbol_files: Collection[str],
    node_counts: Mapping[str, int],
    unreadable: Mapping[str, str],
) -> dict[str, Any]:
    """The coverage of one repository's extraction.

    Args:
        checkout_files: Repository-relative paths in the checkout (outside excluded directories)
        graph_files: The graph's File nodes by repository-relative path, with their ``file_type`` and ``subtype``
        read_by_step: The files the type and method steps read, with how (``parser`` or ``llm``)
        symbol_files: The files that gave at least one type or method
        node_counts: Graph nodes per type
        unreadable: Files a step reads that could not be read, with the reason

    Returns:
        Totals, a row per extension (most files first), the missing and unreadable files in full, the node
        counts, and ``complete`` with the ``reasons`` it is not
    """
    symbols = set(symbol_files)
    by_extension: dict[str, list[str]] = {}
    for path in sorted(set(checkout_files) | set(graph_files)):
        by_extension.setdefault(_extension(path), []).append(path)

    rows = []
    for extension, paths in by_extension.items():
        known = [graph_files[p] for p in paths if p in graph_files]
        rows.append(
            {
                "extension": extension,
                "files": len(paths),
                "in_graph": len(known),
                "file_type": _most_common([f.get("file_type", "") for f in known]),
                "subtype": _most_common([f.get("subtype", "") for f in known]),
                "reader": _most_common([read_by_step[p] for p in paths if p in read_by_step]),
                "with_symbols": sum(1 for p in paths if p in symbols),
                "unreadable": sum(1 for p in paths if p in unreadable),
            }
        )
    rows.sort(key=lambda row: (-row["files"], row["extension"]))

    missing = sorted(p for p in checkout_files if p not in graph_files)
    failed = [{"path": p, "reason": unreadable[p]} for p in sorted(unreadable)]
    unread = sorted(p for p, f in graph_files.items() if f.get("file_type") == "source" and p not in read_by_step)

    reasons = []
    if missing:
        reasons.append(f"{_files(len(missing))} {'is' if len(missing) == 1 else 'are'} not in the graph ({_named(missing)})")
    if failed:
        first = failed[0]
        example = f"{first['path']}: {first['reason']}"
        reasons.append(f"{_files(len(failed))} could not be read ({example if len(failed) == 1 else f'for example {example}'})")
    # Source files and not one type or method: the code layer of the graph is missing
    source = [p for p, f in graph_files.items() if f.get("file_type") == "source"]
    if source and not symbols:
        counts = Counter(_extension(p) for p in source)
        listed = ", ".join(f"{ext} {n}" for ext, n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5])
        reasons.append(f"none of the {len(source)} source file{'s' if len(source) != 1 else ''} gave a type or method ({listed})")

    # By nature or by configuration (shell scripts, a config .js file): worth knowing, not a gap in the run
    notes = []
    if unread:
        counts = Counter(_extension(p) for p in unread)
        listed = ", ".join(f"{ext} ({n})" for ext, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])))
        notes.append(f"{len(unread)} source file{'s' if len(unread) != 1 else ''} {'is' if len(unread) == 1 else 'are'} read by no extraction step: {listed}")
    if symbols:
        for row in rows:
            read = sum(1 for p in by_extension[row["extension"]] if p in read_by_step)
            if read and not row["with_symbols"]:
                notes.append(f"{row['extension']}: none of its {_files(read)} gave a type or method")

    return {
        "files": len(set(checkout_files)),
        "in_graph": sum(1 for p in checkout_files if p in graph_files),
        "extensions": rows,
        "missing": missing,
        "unreadable": failed,
        "nodes": dict(node_counts),
        "complete": not reasons,
        "reasons": reasons,
        "notes": notes,
    }
