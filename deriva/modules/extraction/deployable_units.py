"""Deployable units of a repository, from structure only (no LLM).

A deployable unit is what runs on its own: a container image built from the repository's own
code, an entry point a build manifest declares (a project script, a package with a start
script or bin, a war or a Spring Boot or application build), or a mainframe application
(online and batch). Each unit lists its member files; relationships of the elements made from
those files are lifted to the unit's component. Without any unit, the repository is one.

Pure functions: the caller passes the files, manifest texts, import pairs, mainframe programs,
screens, job runs and calls, and the documentation texts.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class UnitRules:
    """The rules of the DeployableUnit step (extraction config ``params``)."""

    code_subtypes: frozenset[str]  # File subtypes that count as the repository's own code
    container_files: tuple[str, ...] = ("Dockerfile", "Dockerfile.*", "*.Dockerfile")  # Case-insensitive patterns
    readme_lines: int = 8  # Documentation lines kept per unit as naming evidence
    # Web UI signals: page entries and server pages by file name, html-like files inside a template folder
    web_files: tuple[str, ...] = ("index.html", "*.jsp", "*.jspx", "*.cshtml", "*.erb")  # Case-insensitive patterns
    web_template_dirs: tuple[str, ...] = ("templates", "views")
    web_template_suffixes: tuple[str, ...] = (".html", ".htm", ".jinja", ".jinja2", ".j2", ".ftl", ".mustache", ".hbs", ".twig")
    web_excluded_dirs: tuple[str, ...] = ("node_modules", "build", "dist", "target", "test", "tests", "__tests__")


@dataclass
class RepoFacts:
    """What the step reads from the graph and the checkout of one repository (paths carry the repository folder)."""

    repository: str
    files: list[dict[str, Any]]  # {"id", "path", "name", "file_type", "subtype"}
    manifests: dict[str, str] = field(default_factory=dict)  # path -> text (pyproject.toml, package.json, pom.xml, build.gradle)
    imports: list[tuple[str, str]] = field(default_factory=list)  # (importing file, imported file), both in the repository
    programs: list[dict[str, Any]] = field(default_factory=list)  # {"id", "path", "name", "decorators"}
    screens: list[dict[str, Any]] = field(default_factory=list)  # {"id", "path", "name"}
    job_runs: list[tuple[str, str]] = field(default_factory=list)  # (job file, program id)
    program_calls: list[tuple[str, str]] = field(default_factory=list)  # (caller program id, called program id)
    documents: dict[str, str] = field(default_factory=dict)  # documentation path -> text


@dataclass
class Unit:
    """One deployable unit and its members."""

    path: str
    name: str
    kind: str  # container, script, start, bin, war, spring-boot, application, online, batch, module, repository
    evidence: list[str] = field(default_factory=list)
    entry: str | None = None
    members: set[str] = field(default_factory=set)  # File paths
    nodes: set[str] = field(default_factory=set)  # Program and screen node ids (mainframe units)
    manifest_name: str | None = None
    manifest_description: str | None = None
    module: str | None = None
    readme_lines: list[str] = field(default_factory=list)
    readme_title: str | None = None  # First heading of the README in the unit's folder
    web_entries: list[str] = field(default_factory=list)  # Files that serve pages (Web UI signals), sorted


def unit_id(repository: str, unit: Unit) -> str:
    """The unit's graph id: its path (without the repository folder), and its entry or online/batch kind where a folder holds several."""
    relative = unit.path[len(repository) + 1 :] if unit.path.startswith(repository + "/") else ("" if unit.path == repository else unit.path)
    key = relative.replace("/", "_") or repository
    if unit.entry:
        key += f"::{unit.entry}"
    elif unit.kind in ("online", "batch"):
        key += f"::{unit.kind}"
    return f"unit::{repository}::{key}"


def _parent(path: str) -> str:
    return str(PurePosixPath(path).parent)


def _below(path: str, folder: str) -> bool:
    return path.startswith(folder + "/")


def _manifest_entries(path: str, text: str) -> tuple[list[tuple[str, str, str, str]], str | None, str | None]:
    """(kind, entry or "", target or "", evidence) per entry point the manifest declares, and its name and description."""
    name = PurePosixPath(path).name.lower()
    entries: list[tuple[str, str, str, str]] = []
    title = description = None
    if name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return [], None, None
        title, description = data.get("name"), data.get("description")
        if data.get("bin"):
            entries.append(("bin", "", "", f"bin: {path}"))
        elif "start" in (data.get("scripts") or {}):
            entries.append(("start", "", "", f"start script: {path}"))
    elif name == "pom.xml":
        packaging = re.search(r"<packaging>\s*(\w+)\s*</packaging>", text)
        if packaging and packaging.group(1) == "war":
            entries.append(("war", "", "", f"war: {path}"))
        elif "spring-boot-maven-plugin" in text:
            entries.append(("spring-boot", "", "", f"spring-boot: {path}"))
        found = re.search(r"<name>\s*([^<]+?)\s*</name>", text)
        title = found.group(1) if found else None
        found = re.search(r"<description>\s*([^<]+?)\s*</description>", text)
        description = found.group(1) if found else None
    elif name in ("build.gradle", "build.gradle.kts"):
        plugins = set(re.findall(r"""(?:id\s*\(?\s*['"]|apply\s+plugin\s*:\s*['"])([\w.\-]+)['"]""", text)) | set(re.findall(r"^\s*(application|war)\s*$", text, re.MULTILINE))
        for plugin, kind in (("war", "war"), ("org.springframework.boot", "spring-boot"), ("application", "application")):
            if plugin in plugins:
                entries.append((kind, "", "", f"{kind}: {path}"))
                break
    elif name == "pyproject.toml":
        try:
            project = tomllib.loads(text).get("project", {})
        except tomllib.TOMLDecodeError:
            return [], None, None
        title, description = project.get("name"), project.get("description")
        for script, target in sorted((project.get("scripts") or {}).items()):
            entries.append(("script", script, str(target), f"script {script} = {target}: {path}"))
    return entries, title, description


def _script_module(folder: str, target: str, paths: set[str]) -> str | None:
    """The file of a script's entry module (``package.module:function``), in the manifest's folder or its src folder."""
    module = target.split(":", 1)[0].strip().replace(".", "/")
    for base in (folder, f"{folder}/src"):
        for candidate in (f"{base}/{module}.py", f"{base}/{module}/__init__.py", f"{base}/{module}/__main__.py"):
            if candidate in paths:
                return candidate
    return None


def _closure(start: str, imports: dict[str, set[str]]) -> set[str]:
    seen, todo = {start}, [start]
    while todo:
        for target in imports.get(todo.pop(), ()):
            if target not in seen:
                seen.add(target)
                todo.append(target)
    return seen


def _mainframe_units(facts: RepoFacts, imports: dict[str, set[str]]) -> list[Unit]:
    """Per application folder (the parent of the folder holding its programs): the core application splits into online and
    batch, a module nested in it stays one unit. A called program joins the unit of most of its callers (online on a tie)."""
    if not facts.programs:
        return []
    folders = sorted({_parent(_parent(p["path"])) for p in facts.programs})
    cores = [f for f in folders if not any(_below(f, other) for other in folders if other != f)]
    modules = [f for f in folders if f not in cores]
    units: list[Unit] = []
    for module in modules:
        members = {f["path"] for f in facts.files if _below(f["path"], module)}
        nodes = {p["id"] for p in facts.programs if _below(p["path"], module)} | {s["id"] for s in facts.screens if _below(s["path"], module)}
        units.append(
            Unit(
                path=module,
                name=PurePosixPath(module).name,
                kind="module",
                evidence=[f"mainframe module: {module}"],
                members=members,
                nodes=nodes,
                module=PurePosixPath(module).name,
            )
        )

    run_by_job = {program for _, program in facts.job_runs}
    for core in cores:
        programs = {p["id"]: p for p in facts.programs if _below(p["path"], core) and not any(_below(p["path"], m) for m in modules)}
        kind: dict[str, str] = {}
        for pid, p in programs.items():
            tags = {str(d).split(":", 1)[0].lower() for d in p.get("decorators") or []}
            if pid in run_by_job:
                kind[pid] = "batch"
            elif tags & {"online", "cics"}:
                kind[pid] = "online"
        callers: dict[str, list[str]] = defaultdict(list)
        for caller, called in facts.program_calls:
            if caller in programs and called in programs:
                callers[called].append(caller)
        for _ in range(len(programs)):
            changed = False
            for pid in sorted(programs):
                if pid in kind:
                    continue
                votes = Counter(kind[c] for c in callers.get(pid, []) if c in kind)
                if votes or not callers.get(pid):
                    kind[pid] = "batch" if votes["batch"] > votes["online"] else "online"
                    changed = True
            if not changed:
                break
        for pid in programs:
            kind.setdefault(pid, "online")
        screens_by_name = {s["name"].upper(): s for s in facts.screens if _below(s["path"], core)}
        for which in ("online", "batch"):
            chosen = sorted(pid for pid, k in kind.items() if k == which)
            if not chosen:
                continue
            members: set[str] = set()
            nodes: set[str] = set(chosen)
            for pid in chosen:
                path = programs[pid]["path"]
                members.add(path)
                members |= {t for t in imports.get(path, ()) if _below(t, core)}
                for decorator in programs[pid].get("decorators") or []:
                    tag, _, value = str(decorator).partition(":")
                    screen = screens_by_name.get(value.upper()) if tag.lower() in ("map", "mapset") else None
                    if screen:
                        members.add(screen["path"])
                        nodes.add(screen["id"])
            if which == "batch":
                members |= {job for job, program in facts.job_runs if program in nodes and _below(job, core)}
            name = PurePosixPath(core).name
            units.append(Unit(path=core, name=f"{name} {which.title()}", kind=which, evidence=[f"mainframe {which}: {core}"], members=members, nodes=nodes, module=name))
    return units


def _readme_lines(unit: Unit, documents: dict[str, str], limit: int) -> list[str]:
    """The documentation lines that describe a unit: those of the documents in its folder first, then lines naming its folder or entry."""
    if limit <= 0:
        return []
    plain = lambda line: re.sub(r"^[#>*\-\s]+", "", line).strip()  # noqa: E731 - a one-line helper
    lines: list[str] = []
    own = sorted(p for p in documents if _parent(p) == unit.path)
    for path in own:
        lines += [t for line in documents[path].splitlines() if (t := plain(line))]
    names = {PurePosixPath(unit.path).name} | ({unit.entry} if unit.entry else set())
    pattern = re.compile("|".join(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])" for n in sorted(names) if n), re.IGNORECASE)
    for path in sorted(p for p in documents if p not in own):
        lines += [t for line in documents[path].splitlines() if (t := plain(line)) and pattern.search(t)]
    return list(dict.fromkeys(lines))[:limit]


def _readme_title(unit: Unit, documents: dict[str, str]) -> str | None:
    """The first Markdown heading of a README in the unit's own folder."""
    for path in sorted(p for p in documents if _parent(p) == unit.path and PurePosixPath(p).name.lower().startswith("readme")):
        for line in documents[path].splitlines():
            if match := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line):
                # Plain text: images dropped, links as their text, emphasis marks removed
                text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", match.group(1))
                text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
                text = " ".join(re.sub(r"[*_`]+", "", text).split())
                if text:
                    return text
    return None


def _web_entries(unit: Unit, paths: set[str], nested: list[str], rules: UnitRules) -> list[str]:
    """The files in the unit's folder (outside nested units and build, dependency or test folders) that serve pages."""
    names = [n.lower() for n in rules.web_files]
    entries = []
    for path in paths:
        if not _below(path, unit.path) or any(_below(path, other) for other in nested):
            continue
        parts = [part.lower() for part in PurePosixPath(path[len(unit.path) :]).parts[:-1]]
        if any(part in rules.web_excluded_dirs for part in parts):
            continue
        name = PurePosixPath(path).name.lower()
        if any(fnmatch.fnmatchcase(name, n) for n in names) or (any(part in rules.web_template_dirs for part in parts) and name.endswith(rules.web_template_suffixes)):
            entries.append(path)
    return sorted(entries)


def detect_units(facts: RepoFacts, rules: UnitRules) -> list[Unit]:
    """The repository's deployable units, ordered by path and entry."""
    paths = {f["path"] for f in facts.files}
    code = [f["path"] for f in facts.files if f.get("file_type") == "source" and (f.get("subtype") or "") in rules.code_subtypes]
    imports: dict[str, set[str]] = defaultdict(set)
    for source, target in facts.imports:
        imports[source].add(target)

    folder_units: dict[str, Unit] = {}
    script_units: list[Unit] = []
    patterns = [p.lower() for p in rules.container_files]
    for f in sorted(facts.files, key=lambda x: x["path"]):
        if any(fnmatch.fnmatchcase(f["name"].lower(), p) for p in patterns):
            folder = _parent(f["path"])
            if any(_below(c, folder) for c in code):
                unit = folder_units.setdefault(folder, Unit(path=folder, name=PurePosixPath(folder).name, kind="container"))
                unit.evidence.append(f"container: {f['path']}")
    for path, text in sorted(facts.manifests.items()):
        folder = _parent(path)
        entries, title, description = _manifest_entries(path, text)
        for kind, entry, target, evidence in entries:
            if kind == "script":
                module = _script_module(folder, target, paths)
                members = _closure(module, imports) if module else {p for p in paths if _below(p, folder)}
                script_units.append(
                    Unit(path=folder, name=entry, kind="script", evidence=[evidence], entry=entry, members=members, manifest_name=title, manifest_description=description)
                )
                continue
            if not any(_below(c, folder) for c in code):
                continue
            unit = folder_units.setdefault(folder, Unit(path=folder, name=PurePosixPath(folder).name, kind=kind))
            unit.evidence.append(evidence)
        if folder in folder_units:
            folder_units[folder].manifest_name = folder_units[folder].manifest_name or title
            folder_units[folder].manifest_description = folder_units[folder].manifest_description or description

    # A folder that holds another unit folder is no unit itself; project scripts replace their folder's unit
    script_folders = {u.path for u in script_units}
    for folder in list(folder_units):
        if folder in script_folders or any(_below(other, folder) for other in folder_units if other != folder):
            del folder_units[folder]
    for unit in folder_units.values():
        unit.members = {p for p in paths if _below(p, unit.path)}

    units = sorted([*folder_units.values(), *script_units, *_mainframe_units(facts, imports)], key=lambda u: (u.path, u.entry or "", u.kind))
    if not units:
        units = [Unit(path=facts.repository, name=facts.repository, kind="repository", evidence=["no deployable unit found: the repository"], members=set(paths))]
    folders = sorted({u.path for u in units})
    for unit in units:
        unit.readme_lines = _readme_lines(unit, facts.documents, rules.readme_lines)
        unit.readme_title = _readme_title(unit, facts.documents)
        unit.web_entries = _web_entries(unit, paths, [f for f in folders if f != unit.path and _below(f, unit.path)], rules)
    return units
