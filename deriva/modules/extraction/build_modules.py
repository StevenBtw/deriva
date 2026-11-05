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
import posixpath
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
    # A module no unit builds is a component by who uses it (``usage_role``); None leaves that test off
    min_behaviour: float | None = None
    # Decorator patterns of a route-handling file: a unit's feature packages (``feature_areas``) become modules; empty: off
    feature_markers: tuple[str, ...] = ()


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
    grouped: bool = False  # A folder with the same project layout as another one: a module of the design, whoever uses it


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


def csproj_entry(text: str) -> str | None:
    """The kind of program a .NET project builds, None for a class library: ``web`` by the web or worker SDK, ``exe`` by its output type."""
    if re.search(r"""<Project\s[^>]*Sdk\s*=\s*["']Microsoft\.NET\.Sdk\.(Web|Worker)["']""", text):
        return "web"
    return "exe" if re.search(r"<OutputType>\s*(Win)?Exe\s*</OutputType>", text) else None


def declares_entry(path: str, text: str) -> bool:
    """Whether a manifest declares an entry point by its ecosystem's convention: npm ``bin``, ``main`` or a ``start``
    script, a Maven ``mainClass``, the Spring Boot plugin or war packaging, Gradle's application, Spring Boot or war
    plugin, pyproject project scripts, or a .NET project that builds a program."""
    lower = PurePosixPath(path).name.lower()
    if lower.endswith(".csproj"):
        return csproj_entry(text) is not None
    if lower == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return False
        return isinstance(data, dict) and bool(data.get("bin") or data.get("main") or "start" in (data.get("scripts") or {}))
    if lower == "pom.xml":
        return bool(re.search(r"<mainClass>|spring-boot-maven-plugin|<packaging>\s*war\s*</packaging>", text))
    if lower.startswith("build.gradle"):
        return bool(re.search(r"""['"](application|war|org\.springframework\.boot)['"]|^\s*(application|war)\s*$""", text, re.MULTILINE))
    if lower == "pyproject.toml":
        try:
            return bool(tomllib.loads(text).get("project", {}).get("scripts"))
        except tomllib.TOMLDecodeError:
            return False
    return False


def behaviour_per_file(
    code_files: list[str], methods: list[tuple[str, str]], accessors: tuple[str, ...] = ("get", "set", "is"), plain: tuple[str, ...] = ("equals", "hashCode", "toString")
) -> float:
    """Non-accessor methods per code file, on average: accessors (``get``/``set``/``is`` followed by a capital or ``_``),
    the object protocol (``equals``, ``hashCode``, ``toString``) and dunder methods carry no behaviour of their own."""

    def counts(name: str) -> bool:
        if name.startswith("__") or name in plain:
            return False
        return not any(name.startswith(p) and len(name) > len(p) and (name[len(p)].isupper() or name[len(p)] == "_") for p in accessors)

    wanted = set(code_files)
    total = sum(1 for path, name in methods if path in wanted and counts(name))
    return total / len(wanted) if wanted else 0.0


# Why a module and the units inside it are no part of the system itself (the DeployableUnit derivation queries read these too)
_NOT_THE_SYSTEM = frozenset({"infrastructure-as-code", "test-only", "tooling"})


def library_repository(modules: list[BuildModule], unit_paths: list[str]) -> BuildModule | None:
    """The module to keep as the component of a repository that is a library: no module stays a component and every
    unit lies in a test, tooling or infrastructure module, so without it the model would hold no component. The
    outermost module without an entry point takes that role; two at the same depth say nothing, so none does."""
    if any(m.module and m.excluded is None for m in modules):
        return None
    outside = [m.path for m in modules if m.excluded in _NOT_THE_SYSTEM]
    if any(not any(unit == path or unit.startswith(path + "/") for path in outside) for unit in unit_paths):
        return None
    unused = [m for m in modules if m.module and m.excluded == "no entry point"]
    if not unused:
        return None
    depth = min(m.path.count("/") for m in unused)
    top = [m for m in unused if m.path.count("/") == depth]
    return top[0] if len(top) == 1 else None


def usage_role(users: int, behaviour: float, entry: bool, min_behaviour: float) -> str | None:
    """Why a module that no unit builds is no component (None: it is one), by how many units use its code: two or more
    make it a shared library, a component only with behaviour (more than ``min_behaviour`` non-accessor methods per
    code file: a library of data structures has at most its constructors); one makes it part of that unit; none make
    it a standalone program, a component only when its manifest declares an entry point."""
    if users >= 2:
        return None if behaviour > min_behaviour else "data-only library"
    if users == 1:
        return "part of one unit"
    return None if entry else "no entry point"


def source_root(code_files: list[str]) -> str:
    """The deepest folder holding all the code: from the common folder down while it holds one sub-folder and no file."""
    folders = sorted({str(PurePosixPath(p).parent) for p in code_files})
    if not folders:
        return ""
    root = posixpath.commonpath(folders) if len(folders) > 1 else folders[0]
    while True:
        subs = {d[len(root) + 1 :].split("/")[0] for d in folders if d.startswith(root + "/")}
        if len(subs) == 1 and root not in folders:
            root = f"{root}/{subs.pop()}"
            continue
        return root


def feature_areas(code_files: list[str], route_files: set[str], entity_files: set[str]) -> list[str]:
    """The feature packages of a unit: the first-level sub-packages under its source root that hold both a
    route-handling file and a data entity (package by feature). Two or more split the unit; one or none is no split."""
    root = source_root(code_files)
    area_of = lambda p: p[len(root) + 1 :].split("/")[0] if p.startswith(root + "/") and "/" in p[len(root) + 1 :] else None  # noqa: E731 - a one-line helper
    routes = {a for p in code_files if p in route_files and (a := area_of(p))}
    entities = {a for p in code_files if p in entity_files and (a := area_of(p))}
    areas = sorted(f"{root}/{a}" for a in routes & entities)
    return areas if len(areas) >= 2 else []


def repeated_layouts(modules: set[str], manifest_folders: set[str], min_members: int) -> dict[str, list[str]]:
    """Folders without a manifest of their own whose modules repeat another such folder's layout (at least ``min_members``
    of the same names, Application and Domain under both Orders and Billing) -> those modules: one module of the design
    built as several projects. Modules that share no such layout stay as they are."""
    children: dict[str, set[str]] = {}
    for module in modules:
        folder = _parent(module)
        if folder not in manifest_folders:
            children.setdefault(folder, set()).add(PurePosixPath(module).name)
    groups: dict[str, list[str]] = {}
    for folder, names in children.items():
        shared = max((len(names & other) for f, other in children.items() if f != folder), default=0)
        if shared >= min_members:
            groups[folder] = sorted(f"{folder}/{name}" for name in names)
    return groups


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

    def _after_repository(name: str) -> list[str]:
        # What follows the repository's name, a scope or group before it included; else what follows the leading words
        # they share (example-vote-worker in example-voting-app). A name that is only those words keeps them
        words, own = _words(name), [w.casefold() for w in _words(_folder_name(repository))]
        lower = [w.casefold() for w in words]
        for start in range(len(words) - len(own) + 1):
            if lower[start : start + len(own)] == own:
                return words[start + len(own) :]
        shared = next((i for i, (a, b) in enumerate(zip(lower, own, strict=False)) if a != b), min(len(lower), len(own)))
        return words[shared:] if shared < len(words) else words

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
        words = {w.casefold() for w in rules.test_words}
        # The repository's own name says nothing about its code, also in front of a module's name (example-shop-orders)
        if folder != repository:
            own = _after_repository(_folder_name(folder)) + _after_repository(_manifest_name(manifest, manifests.get(manifest, "")) or "")
            # A folder above it counts only when it is a test word itself (examples/demo, not ab-test-service/backend)
            above = folder.removeprefix(repository).strip("/").split("/")[:-1]
            if {w.casefold() for w in own} & words or {part.casefold() for part in above} & words:
                return "test-only"
        return None

    reasons = {folder: reason for folder in code if (reason := excluded(folder))}
    modules = set(code) - set(reasons)
    groups = repeated_layouts(modules, set(candidates), rules.min_members)
    for folder, members in groups.items():
        candidates[folder] = ""
        own[folder] = sorted(path for member in members for path in own.get(member, []))
        modules = (modules - set(members)) | {folder}
    group_of = {member: folder for folder, members in groups.items() for member in members}
    systems: dict[str, list[str]] = {}
    for folder, manifest in candidates.items():
        listed: set[str] = set()
        for pattern in _listed(manifest, manifests.get(manifest, "")):
            target = str(PurePosixPath(folder, pattern.strip("/")))
            listed |= {m for m in set(code) if fnmatch.fnmatchcase(m, target)}
        # Excluded modules count as listed (the aggregation is a fact of the build); its members are the other ones, a
        # grouped project by its group
        members = {group_of.get(m, m) for m in listed} & modules
        if len(listed) >= rules.min_members and members:
            systems[folder] = sorted(members)

    out = []
    raws: dict[str, str] = {}
    kept = sorted(modules | set(systems))
    for folder in sorted(set(kept) | set(reasons)):
        above = [k for k in kept if k != folder and folder.startswith(k + "/")]
        manifest = candidates[folder]
        raw = _manifest_name(manifest, manifests.get(manifest, "")) or _folder_name(folder)
        # A folder that says more than the manifest's name (risk-management-client for "client") names it
        folder_words, raw_words = {w.casefold() for w in _words(_folder_name(folder))}, {w.casefold() for w in _words(raw.rsplit("/", 1)[-1])}
        # An aggregator (a system) is named by its folder, as the root by the repository: its artifactId often carries
        # the packaging (orders-pom, orders-parent)
        if (raw_words and raw_words < folder_words) or folder in systems:
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
                grouped=folder in groups,
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
