"""Benchmark export bundle: one zip with a session folder, its config snapshot and environment, and a sha256 manifest.

Entries are written in sorted order with a fixed timestamp, so the same session exports to
identical bytes; ``verify_bundle`` checks a bundle against its manifest.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deriva.adapters.grafeo import engine_info
from deriva.services import config

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
CHUNK = 1 << 20
# A secret's name ends in key, token, secret or password (api_key, auth_token); max_tokens is a count, not a token
SECRET = re.compile(r"(^|_)(key|token|secret|password)$", re.IGNORECASE)
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = (".py", ".sql")


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _record(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def export_session(session_dir: str | Path, out_path: str | Path, extras: dict[str, Any]) -> dict[str, Any]:
    """Zip ``session_dir`` (under its own name) with ``extras`` as JSON files at the root and a manifest; returns the manifest."""
    session = Path(session_dir)
    out = Path(out_path)
    if not session.is_dir():
        raise FileNotFoundError(f"Benchmark session not found: {session}")
    if out.resolve().is_relative_to(session.resolve()):
        raise ValueError(f"The bundle cannot be written into the session folder it exports: {out}")

    files = sorted((p for p in session.rglob("*") if p.is_file()), key=lambda p: p.relative_to(session).as_posix())
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    entries: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(partial, "w") as bundle:
            for path in files:
                name = f"{session.name}/{path.relative_to(session).as_posix()}"
                digest, size = hashlib.sha256(), 0
                with path.open("rb") as source, bundle.open(_entry(name), "w", force_zip64=path.stat().st_size >= zipfile.ZIP64_LIMIT) as target:
                    for chunk in iter(lambda: source.read(CHUNK), b""):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                entries.append({"path": name, "sha256": digest.hexdigest(), "size": size})
            for name in sorted(extras):
                data = _json_bytes(extras[name])
                bundle.writestr(_entry(name), data)
                entries.append(_record(name, data))
            manifest = {"session_id": session.name, "files": entries}
            bundle.writestr(_entry("manifest.json"), _json_bytes(manifest))
        partial.replace(out)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def verify_bundle(path: str | Path) -> list[str]:
    """Problems found when checking a bundle against its manifest (empty when it verifies)."""
    problems: list[str] = []
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        names = set(bundle.namelist())
        listed = set()
        for entry in manifest["files"]:
            listed.add(entry["path"])
            if entry["path"] not in names:
                problems.append(f"{entry['path']}: missing")
                continue
            digest = hashlib.sha256()
            with bundle.open(entry["path"]) as handle:
                for chunk in iter(lambda: handle.read(CHUNK), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                problems.append(f"{entry['path']}: sha256 differs")
        problems += [f"{name}: not in the manifest" for name in sorted(names - listed - {"manifest.json"})]
    return problems


def public_model_config(config: Any) -> dict[str, Any]:
    """A model config without its secrets (API keys, tokens); the name of the key's variable stays."""
    if dataclasses.is_dataclass(config) and not isinstance(config, type):
        values = dataclasses.asdict(config)
    else:
        values = dict(config) if isinstance(config, Mapping) else dict(vars(config))
    return {k: v for k, v in values.items() if not SECRET.search(k) or k.endswith("_env")}


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False)
        return done.stdout.strip() if done.returncode == 0 else None

    try:
        top = git("rev-parse", "--show-toplevel")
        if top is None or Path(top).resolve() != root.resolve():
            return {"commit": None, "dirty": None}
        status = git("status", "--porcelain")
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}
    except OSError, subprocess.SubprocessError:
        return {"commit": None, "dirty": None}


def source_digest(package_root: str | Path = PACKAGE_ROOT) -> dict[str, Any]:
    """The code that ran: a sha256 over every source file of the package (path and content, caches left out).

    Names the code where a commit cannot: sessions also run on trees with uncommitted changes.
    """
    root = Path(package_root)
    found = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [d for d in subfolders if not d.startswith((".", "__pycache__"))]  # caches are not code
        found += [Path(folder) / n for n in names if Path(n).suffix in SOURCE_SUFFIXES and not n.startswith(".")]
    files = sorted(found, key=lambda p: p.relative_to(root).as_posix())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"files": len(files), "sha256": digest.hexdigest()}


def run_inputs(engine: Any, models: dict[str, Any], config_versions: dict[str, Any] | None = None, llm_samples: dict[str, int] | None = None) -> dict[str, Any]:
    """What a run or session ran on: config versions, LLM samples per step, the tables without version
    history (file types, name patterns, settings) and the environment (code digest, versions, models without secrets).

    ``config_versions`` and ``llm_samples`` default to the active ones (a session passes the snapshot it took).
    """
    return {
        "config_versions": config_versions if config_versions is not None else config.get_active_config_versions(engine),
        "llm_samples": llm_samples if llm_samples is not None else config.llm_samples_per_step(engine),
        "inputs": config.input_snapshot(engine),
        "environment": environment_info(models=models),
    }


def environment_info(models: dict[str, Any] | None = None, repo_root: str | Path = REPO_ROOT, package_root: str | Path = PACKAGE_ROOT) -> dict[str, Any]:
    """Versions (Deriva with its git commit and source digest, grafeo build, solvOR), Python, platform and model configs without secrets."""
    try:
        grafeo = engine_info()
    except Exception as exc:  # the record still helps without the engine's build
        grafeo = {"error": str(exc)}
    return {
        "deriva": _version("Deriva"),
        "git": _git(Path(repo_root)),
        "source": source_digest(package_root),
        "grafeo": grafeo,
        "solvor": _version("solvor"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "models": {name: public_model_config(config) for name, config in sorted((models or {}).items())},
    }
