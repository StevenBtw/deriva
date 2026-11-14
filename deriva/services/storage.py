"""What the workspace keeps on disk, and clearing the parts that can go.

Graph databases (one per repository, the shared ``default`` one, and orphaned ones whose
repository is gone), the LLM response cache, the exported exchange files in workspace/output
and the benchmark sessions. Runs are the studio's own (it measures them itself).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from deriva.adapters.grafeo import DEFAULT_DATABASE, database_bytes, delete_database, list_databases
from deriva.common.cache_utils import cache_contents
from deriva.common.paths import resolve, workspace
from deriva.common.settings import LlmSettings


def _measure(folder: Path, pattern: str = "**/*") -> tuple[int, int]:
    """Bytes and files under a folder (0, 0 when it does not exist)."""
    if not folder.is_dir():
        return 0, 0
    files = [p for p in folder.glob(pattern) if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def _exchange_files(folder: Path) -> list[Path]:
    """The exchange files (``.xml`` in any case: the studio keeps the name it is given) directly in ``folder``."""
    return [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".xml"] if folder.is_dir() else []


def llm_cache_folder() -> Path:
    return resolve(LlmSettings().cache_dir)


def _measure_llm_cache() -> dict[str, Any]:
    """What the LLM cache holds: its cached answers and their bytes (an lmdb map file is as large as its map, most of
    it unused), its files beside; a folder without an lmdb map is measured by its files (entries unknown)."""
    folder = llm_cache_folder()
    size, files = _measure(folder)
    contents = cache_contents(folder) if files else None
    if contents is None:
        return {"bytes": size, "files": files, "entries": None}
    entries, held = contents
    return {"bytes": held, "files": files, "entries": entries}


def exports_folder() -> Path:
    return workspace() / "output"


def overview(repositories: set[str], active: str) -> dict[str, Any]:
    """Sizes per area; each graph database says whether it is a repository's, the shared one or orphaned."""
    graphs: list[dict[str, Any]] = []
    for key in list_databases():
        kind = "repository" if key in repositories else "shared" if key == DEFAULT_DATABASE else "orphaned"
        graphs.append({"key": key, "bytes": database_bytes(key), "kind": kind, "active": key == active})
    graphs.sort(key=lambda g: (-g["bytes"], g["key"]))
    exports = _exchange_files(exports_folder())
    export_bytes, export_files = sum(path.stat().st_size for path in exports), len(exports)
    sessions = workspace() / "benchmarks"
    session_bytes, _ = _measure(sessions)
    return {
        "graphs": graphs,
        "llm_cache": _measure_llm_cache(),
        "exports": {"bytes": export_bytes, "files": export_files},
        "benchmark_sessions": {"bytes": session_bytes, "sessions": sum(1 for p in sessions.iterdir() if p.is_dir()) if sessions.is_dir() else 0},
    }


def clear_llm_cache() -> dict[str, Any]:
    """Delete every cached LLM answer (the next runs call the LLM again); the cache must not be open."""
    folder = llm_cache_folder()
    held = _measure_llm_cache()
    if folder.is_dir():
        for child in folder.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    return held


def list_exports() -> dict[str, Any]:
    """The exported exchange files (*.xml) in workspace/output, newest first, with the folder they are in."""
    folder = exports_folder()
    files = _exchange_files(folder)
    stats = sorted(((path.name, path.stat()) for path in files), key=lambda item: item[1].st_mtime, reverse=True)
    return {
        "folder": str(folder.resolve()),
        "files": [{"name": name, "bytes": stat.st_size, "modified": int(stat.st_mtime)} for name, stat in stats],
    }


def delete_exports() -> dict[str, int]:
    """Delete the exported exchange files (*.xml) in workspace/output; reports and other files stay."""
    folder = exports_folder()
    files = _exchange_files(folder)
    size = sum(path.stat().st_size for path in files)
    for path in files:
        path.unlink()
    return {"bytes": size, "files": len(files)}


def delete_graph(key: str, repositories: set[str], active: str) -> dict[str, Any]:
    """Delete a graph database that belongs to no repository (a repository's goes with the repository's own actions).

    Raises:
        KeyError: no such database
        ValueError: a repository's database, or the open one
    """
    if key not in list_databases():
        raise KeyError(key)
    if key in repositories:
        raise ValueError(f"{key} is a repository's database: clear or delete it on the Repositories page")
    if key == active:
        raise ValueError(f"The database {key!r} is open; switch to another repository before deleting it")
    size = database_bytes(key)
    delete_database(key)
    return {"key": key, "bytes": size}
