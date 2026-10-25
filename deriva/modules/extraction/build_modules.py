"""Build modules of a repository, from structure only (no LLM).

A build module is a folder with a build manifest (the step's versioned list of manifest file names) and code of its
own, files that no deeper module holds. A manifest that aggregates other modules (Maven ``<modules>``, npm, yarn or
pnpm ``workspaces``, a uv workspace's ``members``, Gradle ``include``) and lists at least two of them is a parent
system. Modules nest: a module's parent is the nearest module or system folder above it. Names come from the
manifest (else the folder), with the repository's name dropped from the front.

Pure functions: the caller passes the files and the manifest texts.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from deriva.modules.extraction.deployments import manifest_dependencies


@dataclass(frozen=True)
class ModuleRules:
    """The rules of the BuildModule step (extraction config ``params``)."""

    manifests: tuple[str, ...]  # Build manifest file names (case-insensitive patterns)
    code_subtypes: frozenset[str]  # File subtypes that count as the repository's own code
    min_members: int = 2  # An aggregator is a parent system when it lists at least this many modules
    # A module whose manifest depends on one of these (patterns) is infrastructure as code, no application component
    iac_dependencies: tuple[str, ...] = ()
    # A module whose manifest depends on these only (patterns) holds tests, no application component
    test_dependencies: tuple[str, ...] = ()
    # A module whose folder or manifest name holds one of these words (compared whole) holds tests
    test_words: tuple[str, ...] = ()


@dataclass
class BuildModule:
    path: str
    name: str
    manifest: str  # The manifest file that makes the folder a candidate
    module: bool = False  # Has code of its own
    system: bool = False  # Aggregates at least min_members modules
    parent: str | None = None  # Path of the nearest module or system folder above it
    files: list[str] = field(default_factory=list)  # The files it holds itself, sorted
    members: list[str] = field(default_factory=list)  # For a system: the module paths it lists, sorted
    excluded: str | None = None  # Why it is no application component (infrastructure-as-code, test-only, tooling)


def module_id(repository: str, path: str) -> str:
    """The module's graph id, as unit ids are formed: its path without the repository folder (the repository's name for the root)."""
    relative = path[len(repository) + 1 :] if path.startswith(repository + "/") else ("" if path == repository else path)
    return f"module::{repository}::{relative or repository}"


def _parent(path: str) -> str:
    return str(PurePosixPath(path).parent)


def _words(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def display_name(raw: str, repository: str) -> str:
    """A structural name as a name: a package scope dropped, the repository's name dropped from the front, words title-cased."""
    raw = raw.rsplit("/", 1)[-1] if raw.startswith("@") else raw
    words = _words(raw)
    prefix = [w.casefold() for w in _words(repository)]
    if prefix and [w.casefold() for w in words[: len(prefix)]] == prefix and len(words) > len(prefix):
        words = words[len(prefix) :]
    return " ".join(w[0].upper() + w[1:] if w.islower() else w for w in words)


def _folder_name(folder: str) -> str:
    """A folder's own name; a dotted folder (a qualified name, tools.acme.shop.entities) is named by its last part."""
    name = PurePosixPath(folder).name
    return name.rsplit(".", 1)[-1] if "." in name.strip(".") else name


def _dependencies(path: str, text: str) -> list[str]:
    """The manifest's dependency names, Gradle's map form (group: 'g', name: 'n') included."""
    found = set(manifest_dependencies(path, text))
    if PurePosixPath(path).name.lower().startswith("build.gradle"):
        found |= {n.lower() for n in re.findall(r"""\bname\s*:\s*['"]([\w.\-]+)['"]""", text)}
    return sorted(found)


def _manifest_name(path: str, text: str) -> str | None:
    lower = PurePosixPath(path).name.lower()
    if lower == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return data.get("name") if isinstance(data, dict) and isinstance(data.get("name"), str) else None
    if lower == "pom.xml":
        # The project's own artifactId: the parent's and the dependencies' are left out
        own = re.sub(r"<(parent|dependencies|dependencyManagement|build|profiles)>.*?</\1>", "", text, flags=re.DOTALL)
        found = re.search(r"<artifactId>\s*([^<]+?)\s*</artifactId>", own)
        return found.group(1) if found else None
    if lower == "pyproject.toml":
        try:
            name = tomllib.loads(text).get("project", {}).get("name")
        except tomllib.TOMLDecodeError:
            return None
        return name if isinstance(name, str) else None
    if lower.startswith("settings.gradle"):
        found = re.search(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""", text)
        return found.group(1) if found else None
    return None


def _package_key(name: str) -> str:
    """A package name compared across manifests: lowercase, runs of ``-``, ``_`` and ``.`` as one ``-``."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _requirement(spec: str) -> str:
    """The package name of a requirement string (``shop-web[extra]>=1; python_version > "3"``)."""
    found = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return _package_key(found.group(1)) if found else ""


def _uses(path: str, text: str) -> tuple[set[str], set[str]]:
    """(runtime, development) package names a manifest depends on. Development: dependency groups and dev dependencies
    (pyproject, Poetry), ``devDependencies`` (npm), Maven's test scope; everything else is a runtime use."""
    lower = PurePosixPath(path).name.lower()
    runtime: set[str] = set()
    development: set[str] = set()
    if lower == "pyproject.toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return runtime, development
        project = data.get("project", {})
        poetry = data.get("tool", {}).get("poetry", {})
        runtime |= {_requirement(s) for s in project.get("dependencies", []) if isinstance(s, str)}
        runtime |= {_requirement(s) for group in project.get("optional-dependencies", {}).values() for s in group if isinstance(s, str)}
        runtime |= {_package_key(n) for n in poetry.get("dependencies", {})}
        development |= {_requirement(s) for group in data.get("dependency-groups", {}).values() for s in group if isinstance(s, str)}
        development |= {_requirement(s) for s in data.get("tool", {}).get("uv", {}).get("dev-dependencies", []) if isinstance(s, str)}
        development |= {_package_key(n) for n in poetry.get("dev-dependencies", {})}
        development |= {_package_key(n) for group in poetry.get("group", {}).values() for n in group.get("dependencies", {})}
    elif lower == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return runtime, development
        if isinstance(data, dict):
            runtime |= {_package_key(n) for key in ("dependencies", "peerDependencies", "optionalDependencies") for n in data.get(key) or {}}
            development |= {_package_key(n) for n in data.get("devDependencies") or {}}
    elif lower == "pom.xml":
        used = re.sub(r"<(dependencyManagement|build)>.*?</\1>", "", text, flags=re.DOTALL)
        for block in re.findall(r"<dependency>(.*?)</dependency>", used, re.DOTALL):
            artifact = re.search(r"<artifactId>\s*([^<]+?)\s*</artifactId>", block)
            scope = re.search(r"<scope>\s*([^<]+?)\s*</scope>", block)
            if artifact:
                (development if scope and scope.group(1) == "test" else runtime).add(_package_key(artifact.group(1)))
    return runtime - {""}, development - {""}


def development_only(manifests: dict[str, str]) -> set[str]:
    """The folders of the repository's packages that its manifests list only as a development dependency, never as a
    runtime one: development tooling (a benchmark or test-support package), no part of the system."""
    runtime: set[str] = set()
    development: set[str] = set()
    for path, text in manifests.items():
        used, dev = _uses(path, text)
        runtime |= used
        development |= dev
    folders: set[str] = set()
    for path, text in manifests.items():
        name = _manifest_name(path, text)
        if name and _package_key(name) in development - runtime:
            folders.add(_parent(path))
    return folders


def _listed(path: str, text: str) -> list[str]:
    """The member folders an aggregator manifest lists (relative patterns, as written)."""
    lower = PurePosixPath(path).name.lower()
    if lower == "pom.xml":
        block = re.search(r"<modules>(.*?)</modules>", text, re.DOTALL)
        return re.findall(r"<module>\s*([^<]+?)\s*</module>", block.group(1)) if block else []
    if lower == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        spaces = data.get("workspaces") if isinstance(data, dict) else None
        spaces = spaces.get("packages") if isinstance(spaces, dict) else spaces
        return [str(s) for s in spaces] if isinstance(spaces, list) else []
    if lower == "pyproject.toml":
        try:
            tool = tomllib.loads(text).get("tool", {})
        except tomllib.TOMLDecodeError:
            return []
        members = (tool.get("uv", {}).get("workspace", {}) or {}).get("members") or []
        return [str(m) for m in members] if isinstance(members, list) else []
    if lower.startswith("settings.gradle"):
        found: list[str] = []
        for line in re.findall(r"^\s*include\s*\(?(.+?)\)?\s*$", text, re.MULTILINE):
            found += [name.lstrip(":").replace(":", "/") for name in re.findall(r"""['"]([^'"]+)['"]""", line)]
        return found
    return []


def detect_modules(repository: str, files: list[dict[str, Any]], manifests: dict[str, str], rules: ModuleRules) -> list[BuildModule]:
    """The build modules and parent systems of a repository, sorted by path.

    Args:
        repository: The repository name (the first folder of every path)
        files: {"path", "name", "file_type", "subtype"} of the repository's files
        manifests: Manifest path -> text (for names and aggregation)
        rules: The step's rules
    """
    patterns = [p.lower() for p in rules.manifests]
    candidates: dict[str, str] = {}
    for f in sorted(files, key=lambda f: f["path"]):
        if any(fnmatch.fnmatchcase(str(f["name"]).lower(), p) for p in patterns):
            candidates.setdefault(_parent(str(f["path"])), str(f["path"]))

    def holder(path: str) -> str | None:
        folder = _parent(path)
        while True:
            if folder in candidates:
                return folder
            if folder in (repository, ".", "") or "/" not in folder:
                return folder if folder in candidates else None
            folder = _parent(folder)

    own: dict[str, list[str]] = {}
    code: set[str] = set()
    for f in files:
        folder = holder(str(f["path"]))
        if folder is not None:
            own.setdefault(folder, []).append(str(f["path"]))
            if f.get("file_type") == "source" and f.get("subtype") in rules.code_subtypes:
                code.add(folder)

    tooling = development_only(manifests)

    def excluded(folder: str) -> str | None:
        manifest = candidates[folder]
        if folder in tooling:
            return "tooling"
        dependencies = _dependencies(manifest, manifests.get(manifest, ""))
        matches = lambda name, patterns: any(fnmatch.fnmatchcase(name, p.lower()) for p in patterns)  # noqa: E731 - a one-line helper
        if any(matches(d, rules.iac_dependencies) for d in dependencies):
            return "infrastructure-as-code"
        if rules.test_dependencies and dependencies and all(matches(d, rules.test_dependencies) for d in dependencies):
            return "test-only"
        named = {w.casefold() for w in _words(_folder_name(folder)) + _words(_manifest_name(manifest, manifests.get(manifest, "")) or "")}
        if named & {w.casefold() for w in rules.test_words}:
            return "test-only"
        return None

    reasons = {folder: reason for folder in code if (reason := excluded(folder))}
    modules = set(code) - set(reasons)
    systems: dict[str, list[str]] = {}
    for folder, manifest in candidates.items():
        listed: set[str] = set()
        for pattern in _listed(manifest, manifests.get(manifest, "")):
            target = str(PurePosixPath(folder, pattern.strip("/")))
            listed |= {m for m in modules if fnmatch.fnmatchcase(m, target)}
        if len(listed) >= rules.min_members:
            systems[folder] = sorted(listed)

    out = []
    raws: dict[str, str] = {}
    kept = sorted(modules | set(systems))
    for folder in sorted(set(kept) | set(reasons)):
        above = [k for k in kept if k != folder and folder.startswith(k + "/")]
        manifest = candidates[folder]
        raw = _manifest_name(manifest, manifests.get(manifest, "")) or _folder_name(folder)
        # A folder that says more than the manifest's name (risk-management-client for "client") names it
        folder_words, raw_words = {w.casefold() for w in _words(_folder_name(folder))}, {w.casefold() for w in _words(raw.rsplit("/", 1)[-1])}
        if raw_words and raw_words < folder_words:
            raw = _folder_name(folder)
        raws[folder] = raw
        out.append(
            BuildModule(
                path=folder,
                name=display_name(raw, repository),
                manifest=manifest,
                module=folder in modules,
                system=folder in systems,
                parent=sorted(above, key=lambda p: (len(p), p))[-1] if above else None,
                files=sorted(own.get(folder, [])),
                members=systems.get(folder, []),
                excluded=reasons.get(folder),
            )
        )
    # The root holds the repository: it takes the repository's name (an aggregator's own name is often "parent")
    for m in out:
        if m.path == repository:
            m.name = display_name(repository, "")
    _settle_collisions([m for m in out if m.excluded is None and m.path != repository], raws, repository)
    return out


def _settle_collisions(modules: list[BuildModule], raws: dict[str, str], repository: str) -> None:
    """Names two modules share: first the full manifest name (the repository's name kept); then the module whose folder
    carries the manifest name keeps it and the others take their folder name; then the words of their path."""

    def colliding() -> list[BuildModule]:
        counts: dict[str, int] = {}
        for m in modules:
            counts[m.name.casefold()] = counts.get(m.name.casefold(), 0) + 1
        return [m for m in modules if counts[m.name.casefold()] > 1]

    for m in colliding():
        m.name = display_name(raws[m.path], "")
    clashes = colliding()
    for m in clashes:
        carries = _folder_name(m.path).casefold() == raws[m.path].rsplit("/", 1)[-1].casefold()
        if not carries or sum(1 for o in clashes if o.name.casefold() == m.name.casefold() and _folder_name(o.path).casefold() == raws[o.path].rsplit("/", 1)[-1].casefold()) > 1:
            m.name = display_name(_folder_name(m.path), repository)
    for m in colliding():
        m.name = display_name(m.path[len(repository) + 1 :].replace("/", " "), repository)
