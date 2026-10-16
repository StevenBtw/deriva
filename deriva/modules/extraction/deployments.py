"""Deployment structure (no LLM): the environments a repository deploys to and the services they run.

An environment is one deployment kind: a compose file (``Docker Compose``), the Kubernetes manifests
(``Kubernetes``) or the cloud templates and CDK apps (``AWS ECS``). Each runs services; a service is matched
to the deployable unit it builds or runs (by build context, else by its image or name), or stays without a
unit when it runs a ready-made image (``postgres:15``). One environment is the primary one (the cloud, else
the root compose file, else Kubernetes); the others are reported. A managed cloud service is qualified by a
property (an engine) where the rules name one, so its name can carry it. The runtime image of a container unit
is the last ``FROM`` of its Dockerfile.

``technology_layer`` adds the system software: images, runtimes (a project-built image resolved to
its base through its build command and FROM chain), managed cloud services, content markers and
manifest dependencies, matched to the closed list (``technologies``). Subsystems that content markers
find make a mainframe environment when there is no other one.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from deriva.modules.extraction.technologies import Technology, image_name, match_technology

_WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


@dataclass(frozen=True)
class DeploymentRules:
    """The signals of the Deployment step (extraction config ``params``)."""

    # Cloud resource type -> role: "container" (a deployed service), "function" or "managed" (a managed service)
    cloud_resources: tuple[tuple[str, str], ...] = ()
    # Cloud resource type -> (property, default): the property's value qualifies the type (``AWS::RDS::DBInstance::postgres``)
    cloud_qualifiers: tuple[tuple[str, str, str], ...] = ()
    # CDK construct ("module.Class") -> (CloudFormation type, environment name or "", fixed properties): read statically
    cdk_constructs: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = ()
    compose_files: tuple[str, ...] = ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml")
    environment_names: tuple[tuple[str, str], ...] = (("compose", "Docker Compose"), ("kubernetes", "Kubernetes"), ("cloud", "AWS ECS"), ("mainframe", "Mainframe"))
    # Files whose image build commands name a project's own images (scripts relative to their folder, YAML to the root)
    build_scripts: tuple[str, ...] = ("*.sh", "*.bash", "makefile", "*.mk", "*.yml", "*.yaml")
    # Content markers: (pattern, technology alias); a source file matching the pattern uses that technology
    markers: tuple[tuple[str, str], ...] = ()
    # Source file suffixes searched for content markers
    marker_suffixes: tuple[str, ...] = ()
    # Manifest file pattern -> runtime alias, for a deployed unit without a container base image
    manifest_runtimes: tuple[tuple[str, str], ...] = ()


@dataclass
class DeployedService:
    """A service an environment runs, with the unit it deploys (None for a ready-made image)."""

    name: str
    unit: str | None = None
    image: str | None = None
    kind: str = "service"  # service (compose, Kubernetes) or container (cloud)
    depends_on: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    ports: list[int] = field(default_factory=list)  # Published and container ports (compose)


@dataclass
class Environment:
    kind: str  # compose, kubernetes, cloud
    name: str
    file: str  # The compose file, the folder of the manifests or of the templates
    services: list[DeployedService] = field(default_factory=list)
    managed: list[str] = field(default_factory=list)  # Managed service resource types (cloud)


@dataclass
class DeploymentResult:
    primary: Environment | None = None
    others: list[Environment] = field(default_factory=list)
    base_images: dict[str, list[str]] = field(default_factory=dict)  # unit id -> runtime image of its Dockerfile(s)
    managed: list[str] = field(default_factory=list)  # Managed service resource types of every cloud template


class _TolerantLoader(yaml.SafeLoader):
    """A YAML loader that reads CloudFormation short-form tags (``!Ref``, ``!Sub``...) as their plain value."""


def _tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_TolerantLoader.add_multi_constructor("!", _tag)


def _documents(text: str) -> list[Any]:
    try:
        return [d for d in yaml.load_all(text, Loader=_TolerantLoader) if d is not None]
    except yaml.YAMLError:
        return []


def _parent(path: str) -> str:
    return str(PurePosixPath(path).parent)


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part == "..":
            parts = parts[:-1]
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts)


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.casefold()) if t]


class _Units:
    """Unit lookup by folder, by the last word of its name, by folder name."""

    def __init__(self, units: list[dict[str, Any]]):
        self.units = units
        last: dict[str, list[str]] = {}
        for u in units:
            words = _tokens(str(u.get("name") or PurePosixPath(str(u["path"])).name))
            if words:
                last.setdefault(words[-1], []).append(str(u["id"]))
        self.by_last = {word: ids[0] for word, ids in last.items() if len(ids) == 1}

    def by_folder(self, folder: str) -> str | None:
        exact = [u for u in self.units if u["path"] == folder]
        if exact:
            return str(exact[0]["id"])
        below = [u for u in self.units if str(u["path"]).startswith(folder + "/")]
        return str(below[0]["id"]) if len(below) == 1 else None

    def holding(self, path: str) -> str | None:
        """The deepest unit whose folder holds a path."""
        holders = self.holders(path)
        return holders[0] if holders else None

    def holders(self, path: str) -> list[str]:
        """The units with the deepest folder that holds a path, by id; units that share that folder are told
        apart by their ``members`` (file paths) when one lists the path, else all of them hold it."""
        holders = [u for u in self.units if path.startswith(str(u["path"]) + "/")]
        deepest = max((len(str(u["path"])) for u in holders), default=0)
        nearest = [u for u in holders if len(str(u["path"])) == deepest]
        listing = [u for u in nearest if path in (u.get("members") or ())]
        return sorted(str(u["id"]) for u in (listing or nearest))

    def by_exact_name(self, names: list[str]) -> str | None:
        """The one unit whose name or folder name is one of the names (case-insensitive), first name first."""
        for name in names:
            found = [u for u in self.units if name.casefold() in (str(u.get("name") or "").casefold(), PurePosixPath(str(u["path"])).name.casefold())]
            if len(found) == 1:
                return str(found[0]["id"])
        return None

    def by_name(self, *names: str | None) -> str | None:
        for name in names:
            words = _tokens(image_name(name)) if name else []
            if words and words[-1] in self.by_last:
                return self.by_last[words[-1]]
        return None


def _compose(path: str, text: str, units: _Units, rules: DeploymentRules) -> Environment | None:
    docs = _documents(text)
    services = docs[0].get("services") if docs and isinstance(docs[0], dict) else None
    if not isinstance(services, dict):
        return None
    env = Environment(kind="compose", name=dict(rules.environment_names).get("compose", "Docker Compose"), file=path)
    for name, spec in services.items():
        spec = spec if isinstance(spec, dict) else {}
        build = spec.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        unit = units.by_folder(_normalize(f"{_parent(path)}/{context}")) if isinstance(context, str) else None
        image = spec.get("image") if isinstance(spec.get("image"), str) else None
        unit = unit or (units.by_name(image, str(name)) if (image or not context) else None)
        depends = spec.get("depends_on") or []
        variables = spec.get("environment") or {}
        if isinstance(variables, list):
            variables = dict(v.split("=", 1) if "=" in v else (v, "") for v in variables if isinstance(v, str))
        env.services.append(
            DeployedService(
                name=str(name),
                unit=unit,
                image=image,
                depends_on=sorted(str(d) for d in (depends if isinstance(depends, list) else depends.keys())),
                environment={str(k): str(v) for k, v in variables.items()} if isinstance(variables, dict) else {},
                ports=_ports(spec.get("ports")),
            )
        )
    return env


def _ports(entries: Any) -> list[int]:
    """The port numbers of compose ``ports`` entries ("8080:80", "127.0.0.1:5432:5432", 9000, {target, published})."""
    found: set[int] = set()
    for entry in entries if isinstance(entries, list) else []:
        values = [entry.get("target"), entry.get("published")] if isinstance(entry, dict) else str(entry).split("/")[0].split(":")
        found |= {int(v) for v in values if str(v).isdigit()} - {0}
    return sorted(p for p in found if p < 65536)


def _kubernetes(manifests: dict[str, list[Any]], units: _Units, rules: DeploymentRules) -> Environment | None:
    services: list[DeployedService] = []
    for _, docs in sorted(manifests.items()):
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") not in _WORKLOADS:
                continue
            name = str((doc.get("metadata") or {}).get("name") or "")
            spec = doc.get("spec") or {}
            template = (spec.get("jobTemplate") or {}).get("spec", spec) if doc.get("kind") == "CronJob" else spec
            containers = ((template.get("template") or {}).get("spec") or {}).get("containers") or []
            image = next((c.get("image") for c in containers if isinstance(c, dict) and isinstance(c.get("image"), str)), None)
            services.append(DeployedService(name=name, unit=units.by_name(name, image), image=image))
    if not services:
        return None
    folders = [PurePosixPath(p).parent.parts for p in manifests]
    common = [parts[0] for parts in zip(*folders, strict=False) if len(set(parts)) == 1]
    return Environment(kind="kubernetes", name=dict(rules.environment_names).get("kubernetes", "Kubernetes"), file="/".join(common), services=services)


def _qualified(kind: str, resource: dict[str, Any], rules: DeploymentRules) -> str:
    """The resource type with its qualifier (``AWS::RDS::DBInstance::postgres``), or the plain type."""
    for qualified_type, prop, default in rules.cloud_qualifiers:
        if qualified_type == kind:
            properties = resource.get("Properties")
            value = properties.get(prop) if isinstance(properties, dict) else None
            value = value if isinstance(value, str) and value else default
            return f"{kind}::{value.lower()}" if value else kind
    return kind


def _cloud(templates: dict[str, dict[str, Any]], units: _Units, rules: DeploymentRules) -> tuple[Environment | None, list[str]]:
    """The cloud environment of the templates and CDK apps. A CDK container carries its names (matched to a unit by
    name) and the environment its construct runs in; a template container deploys the unit that holds the template."""
    roles = dict(rules.cloud_resources)
    services: list[DeployedService] = []
    managed: set[str] = set()
    names: set[str] = set()
    for path, resources in sorted(templates.items()):
        for logical, resource in sorted(resources.items()):
            kind = resource.get("Type") if isinstance(resource, dict) else None
            role = roles.get(str(kind)) if kind else None
            if role == "container":
                named = resource.get("Names")
                unit = units.by_exact_name([str(n) for n in named]) if isinstance(named, list) else units.holding(path)
                services.append(DeployedService(name=str(logical), unit=unit, kind="container"))
                if resource.get("Environment"):
                    names.add(str(resource["Environment"]))
            elif role in ("function", "managed"):
                managed.add(_qualified(str(kind), resource, rules))
    if not services:
        return None, sorted(managed)
    folders = [PurePosixPath(p).parent.parts for p in templates]
    common = [parts[0] for parts in zip(*folders, strict=False) if len(set(parts)) == 1]
    name = next(iter(names)) if len(names) == 1 else dict(rules.environment_names).get("cloud", "Cloud")
    env = Environment(kind="cloud", name=name, file="/".join(common), services=services, managed=sorted(managed))
    return env, sorted(managed)


def _last_from(text: str) -> str | None:
    images = [m.group(1) for m in re.finditer(r"(?im)^\s*FROM\s+(?:--\S+\s+)*(\S+)", text)]
    return images[-1] if images else None


def detect_deployments(
    repository: str,
    files: dict[str, str],
    units: list[dict[str, Any]],
    rules: DeploymentRules,
    cdk: dict[str, dict[str, Any]] | None = None,
) -> DeploymentResult:
    """The deployment environments of a repository.

    Args:
        repository: The repository name (the first folder of every path)
        files: Path -> text of the candidate deployment files (compose, YAML/JSON manifests and templates, Dockerfiles)
        units: {"id", "path", "name"} of the deployable units
        rules: The signals
        cdk: Path -> the resources a CDK app file declares (template-shaped, with ``Names``), read with the templates
    """
    lookup = _Units(units)
    result = DeploymentResult()
    environments: list[Environment] = []
    manifests: dict[str, list[Any]] = {}
    templates: dict[str, dict[str, Any]] = {}
    runtimes: dict[str, list[tuple[int, str]]] = {}  # unit id -> (folders below the unit, image)
    by_id = {str(u["id"]): str(u["path"]) for u in units}
    for path, text in sorted(files.items()):
        name = PurePosixPath(path).name
        lower = name.lower()
        if _is_dockerfile(lower):
            unit = lookup.holding(path) or lookup.by_folder(_parent(path))
            if unit and (image := _last_from(text)):
                depth = len(PurePosixPath(path).relative_to(by_id[unit]).parts) if path.startswith(by_id[unit] + "/") else 0
                runtimes.setdefault(unit, []).append((depth, image))
            continue
        if any(fnmatch.fnmatchcase(lower, p) for p in rules.compose_files):
            if env := _compose(path, text, lookup, rules):
                environments.append(env)
            continue
        if lower.endswith((".yaml", ".yml", ".json")):
            docs = _documents(text) if not lower.endswith(".json") else _json(text)
            if any(isinstance(d, dict) and d.get("kind") in _WORKLOADS for d in docs):
                manifests[path] = docs
            for doc in docs:
                if (
                    isinstance(doc, dict)
                    and isinstance(doc.get("Resources"), dict)
                    and any(isinstance(r, dict) and str(r.get("Type", "")).startswith(("AWS::", "Microsoft.", "Google")) for r in doc["Resources"].values())
                ):
                    templates[path] = doc["Resources"]
    templates.update(cdk or {})
    # A unit's own Dockerfile decides its runtime; a nested one (an example, a sidecar) only when it has none
    for unit, found in runtimes.items():
        nearest = min(depth for depth, _ in found)
        result.base_images[unit] = [image for depth, image in found if depth == nearest]
    if kube := _kubernetes(manifests, lookup, rules):
        environments.append(kube)
    cloud, managed = _cloud(templates, lookup, rules)
    result.managed = managed
    if cloud:
        environments.append(cloud)
    order = {"cloud": 0, "compose": 1, "kubernetes": 2}
    ranked = sorted(environments, key=lambda e: (order[e.kind], len(PurePosixPath(e.file).parts), e.file))
    if ranked:
        result.primary, result.others = ranked[0], ranked[1:]
    return result


def manifest_dependencies(path: str, text: str) -> list[str]:
    """The dependency names a manifest declares (lowercase, sorted): pom.xml artifactIds, package.json
    (dev)dependencies, pyproject [project] dependencies, requirements*.txt lines, Gradle coordinates."""
    name = PurePosixPath(path).name.lower()
    found: list[str] = []
    if name == "pom.xml":
        found = re.findall(r"<dependency>\s*<groupId>[^<]*</groupId>\s*<artifactId>([^<]+)</artifactId>", text)
    elif name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        if isinstance(data, dict):
            found = [str(k) for key in ("dependencies", "devDependencies") if isinstance(data.get(key), dict) for k in data[key]]
    elif name == "pyproject.toml":
        import tomllib

        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            data = {}
        found = [re.split(r"[<>=!~\[; ]", str(d))[0] for d in (data.get("project") or {}).get("dependencies") or []]
    elif name.startswith("requirements") and name.endswith(".txt"):
        found = [re.split(r"[<>=!~\[; ]", line.strip())[0] for line in text.splitlines() if line.strip() and not line.strip().startswith(("#", "-"))]
    elif name in ("build.gradle", "build.gradle.kts"):
        found = re.findall(r"['\"][\w.\-]+:([\w.\-]+)(?::[\w.\-]+)?['\"]", text)
    return sorted({d.strip().lower() for d in found if d.strip()})


def _json(text: str) -> list[Any]:
    try:
        return [json.loads(text)]
    except ValueError:
        return []


def _is_dockerfile(lower_name: str) -> bool:
    return lower_name == "dockerfile" or lower_name.startswith("dockerfile.") or lower_name.endswith(".dockerfile")


# Flags of an image build that take a value (the context is the positional argument that remains)
_BUILD_VALUE_FLAGS = {
    "-t", "--tag", "-f", "--file", "--build-arg", "--platform", "--target", "--label", "--cache-from", "--cache-to",
    "--network", "--progress", "-o", "--output", "--secret", "--ssh", "--builder", "--build-context", "--iidfile", "--metadata-file",
}  # fmt: skip
_VARIABLE = re.compile(r"\$\{[^}]*\}|\$\w+")


def _build_commands(text: str) -> list[list[str]]:
    """The argument lists after ``docker build`` / ``docker buildx build`` in a script (continuations joined)."""
    joined = re.sub(r"\\\r?\n", " ", text)
    commands: list[list[str]] = []
    for line in joined.splitlines():
        for match in re.finditer(r"\bdocker\s+(?:buildx\s+)?build\s+(.*)", line):
            rest = re.split(r"\s(?:&&|\|\||;|\|)\s", match.group(1))[0]
            try:
                commands.append(shlex.split(rest, comments=True))
            except ValueError:
                continue
    return commands


def built_images(repository: str, files: dict[str, str], scripts: tuple[str, ...]) -> dict[str, str]:
    """The project's own images: image name -> the Dockerfile its build command builds.

    A build command (``docker build -t IMAGE [-f FILE] CONTEXT`` in a script or CI file) names
    the image; variables in the tag (a registry prefix) are dropped, a tag that is only a variable
    names no image. The context of a shell script or makefile is relative to its folder, of a YAML
    file (CI) to the repository root.
    """
    built: dict[str, str] = {}
    for path, text in sorted(files.items()):
        lower = PurePosixPath(path).name.lower()
        if not any(fnmatch.fnmatchcase(lower, p) for p in scripts):
            continue
        base = repository if lower.endswith((".yml", ".yaml")) else _parent(path)
        for args in _build_commands(text):
            tags: list[str] = []
            dockerfile: str | None = None
            positional: list[str] = []
            i = 0
            while i < len(args):
                arg = args[i]
                flag, _, inline = arg.partition("=")
                if flag in _BUILD_VALUE_FLAGS:
                    value = inline if inline else (args[i + 1] if i + 1 < len(args) else "")
                    i += 1 if inline else 2
                    if flag in ("-t", "--tag"):
                        tags.append(value)
                    elif flag in ("-f", "--file"):
                        dockerfile = value
                    continue
                if not arg.startswith("-"):
                    positional.append(arg)
                i += 1
            if not positional or _VARIABLE.search(positional[-1]):
                continue
            context = _normalize(f"{base}/{positional[-1]}")
            target = _normalize(f"{base}/{dockerfile}") if dockerfile else f"{context}/Dockerfile"
            for tag in tags:
                name = image_name(_VARIABLE.sub("", tag))
                if name and re.match(r"[a-z0-9]", name):
                    built.setdefault(name, target)
    return built


def resolve_image(image: str, built: dict[str, str], files: dict[str, str]) -> str:
    """The ready-made image a project's own image is built on: follows build commands and FROM chains.

    An image is the project's own when a build command names it (exactly, or by its last path segment
    when that segment names one built image); its Dockerfile's last FROM is followed until an image no
    build command names.
    """
    last: dict[str, list[str]] = {}
    for name in built:
        last.setdefault(name.rsplit("/", 1)[-1], []).append(name)
    name = image_name(image)
    seen: set[str] = set()
    while name not in seen:
        seen.add(name)
        segment = name.rsplit("/", 1)[-1]
        own = built.get(name) or (built[last[segment][0]] if len(last.get(segment, [])) == 1 else None)
        base = _last_from(files.get(own, "")) if own else None
        if not base:
            break
        name = image_name(base)
    return name


def content_markers(sources: dict[str, str], markers: tuple[tuple[str, str], ...]) -> dict[str, list[str]]:
    """Technology alias -> the source files whose text matches its marker (case-insensitive), sorted."""
    compiled = [(re.compile(pattern, re.IGNORECASE), alias) for pattern, alias in markers]
    found: dict[str, list[str]] = {}
    for path, text in sorted(sources.items()):
        for pattern, alias in compiled:
            if pattern.search(text) and path not in found.get(alias, []):
                found.setdefault(alias, []).append(path)
    return found


@dataclass
class Software:
    """A system software of the technology layer: on the closed list (``listed``) or a fallback image."""

    name: str
    kind: str
    listed: bool
    evidence: list[str] = field(default_factory=list)
    in_environment: bool = False  # Runs in the primary environment (its image, a unit's runtime, a managed service, a subsystem)
    serves: list[str] = field(default_factory=list)  # Unit ids that demonstrably use it


@dataclass
class TechnologyLayer:
    deployments: DeploymentResult
    environment: Environment | None = None  # The primary environment (or the mainframe one)
    deployed: list[str] = field(default_factory=list)  # Unit ids the environment runs (every unit without one)
    software: list[Software] = field(default_factory=list)
    unconnected: list[str] = field(default_factory=list)  # Software left out: no environment holds it and no unit uses it


def _references(value: str, host: str) -> bool:
    """A connection value names a service as its host (``postgres://db:5432``, ``user@db``, ``db``)."""
    return re.search(rf"(?:^|[/@=,\s]){re.escape(host)}(?=$|[:/,\s])", value) is not None


def technology_layer(
    repository: str,
    files: dict[str, str],
    units: list[dict[str, Any]],
    rules: DeploymentRules,
    catalog: tuple[Technology, ...],
    sources: dict[str, str],
    cdk: dict[str, dict[str, Any]] | None = None,
) -> TechnologyLayer:
    """The primary environment, the units it runs and the system software with its evidence.

    Software comes from the environment's ready-made images, the deployed units' runtime images (a
    project-built image resolved to its base), managed cloud services, content markers and the deployed
    units' manifest dependencies, each matched to the closed list; an image off the list is kept as
    fallback software, a dependency off the list is a library and left out. Software runs in the
    environment when an image, runtime, managed service or subsystem puts it there; it serves a unit
    on demonstrable use (the unit's runtime, a depends_on or a connection value naming its service, a
    manifest dependency, a marker file in the unit); a unit the environment does not run is still served
    by its own runtime, outside the environment. Without another environment, subsystems found by
    markers make a mainframe environment that runs the units holding the marker files.

    Args:
        repository: The repository name (the first folder of every path)
        files: Path -> text of the deployment files, build scripts and manifests
        units: {"id", "path", "name"} of the deployable units
        rules: The signals
        catalog: The closed list of technologies
        sources: Path -> text of the source files searched for content markers
        cdk: Path -> the resources of the CDK app files (see ``detect_deployments``)
    """
    deployments = detect_deployments(repository, files, units, rules, cdk)
    layer = TechnologyLayer(deployments=deployments, environment=deployments.primary)
    lookup = _Units(units)
    built = built_images(repository, files, rules.build_scripts)
    marked = {alias: paths for alias, paths in content_markers(sources, rules.markers).items() if match_technology(alias, catalog)}
    if layer.environment is None and marked:
        holders = sorted({unit for paths in marked.values() for p in paths for unit in lookup.holders(p)})
        names = {str(u["id"]): str(u.get("name") or PurePosixPath(str(u["path"])).name) for u in units}
        layer.environment = Environment(
            kind="mainframe",
            name=dict(rules.environment_names).get("mainframe", "Mainframe"),
            file="",
            services=[DeployedService(name=names[unit], unit=unit) for unit in holders],
        )
    env = layer.environment
    layer.deployed = sorted({s.unit for s in env.services if s.unit}) if env else sorted(str(u["id"]) for u in units)
    deployed = set(layer.deployed)

    software: dict[str, Software] = {}

    def add(alias: str, evidence: str, *, in_environment: bool = False, serves: tuple[str, ...] = (), fallback: bool = False, outside: str | None = None) -> None:
        # serves: the deployed units among them; outside: a unit the environment does not run, served all the same
        tech = match_technology(alias, catalog)
        if tech is None and not fallback:
            return
        key = tech.name if tech else alias
        entry = software.setdefault(key, Software(name=key, kind=tech.kind if tech else "fallback", listed=tech is not None))
        if evidence not in entry.evidence:
            entry.evidence.append(evidence)
        entry.in_environment |= in_environment and env is not None
        entry.serves = sorted(set(entry.serves) | {u for u in serves if u in deployed} | ({outside} if outside else set()))

    if env:
        for service in env.services:
            if service.unit is None and service.image:
                users = tuple(s.unit for s in env.services if s.unit and (service.name in s.depends_on or any(_references(v, service.name) for v in s.environment.values())))
                add(resolve_image(service.image, built, files), f"image of {service.name}", in_environment=True, serves=users, fallback=True)
    for unit, images in sorted(deployments.base_images.items()):
        for image in images:
            if unit in deployed:
                add(resolve_image(image, built, files), f"runtime of {unit}", in_environment=True, serves=(unit,), fallback=True)
            else:
                # A unit the environment does not run is still served by its own runtime, outside the environment
                add(resolve_image(image, built, files), f"runtime of {unit} (outside the environment)", fallback=True, outside=unit)
    if env and env.kind == "cloud":
        for kind in env.managed:
            # A qualified type (an engine) off the list falls back to its plain type
            alias = kind.lower()
            if match_technology(alias, catalog) is None and alias.count("::") > 2:
                alias = alias.rsplit("::", 1)[0]
            add(alias, "cloud template", in_environment=True)
    for alias, paths in sorted(marked.items()):
        holders = tuple(sorted({unit for p in paths for unit in lookup.holders(p)}))
        add(alias, f"marker in {len(paths)} files", in_environment=True, serves=holders)
    for path, text in sorted(files.items()):
        lower = PurePosixPath(path).name.lower()
        dependencies = manifest_dependencies(path, text)
        runtime = next((alias for pattern, alias in rules.manifest_runtimes if fnmatch.fnmatchcase(lower, pattern)), None)
        if not dependencies and runtime is None:
            continue
        for holder in lookup.holders(path):
            if holder not in deployed:
                continue
            for dependency in dependencies:
                add(dependency, f"dependency of {holder}", serves=(holder,))
            if runtime and holder not in deployments.base_images:
                add(runtime, f"manifest of {holder}", serves=(holder,))

    # A driver-detected engine (not running in the environment itself) is the managed service of that engine
    # when the environment has one: the qualifier names the engine; its evidence and users move to the service
    for kind in env.managed if env and env.kind == "cloud" else []:
        parts = kind.lower().split("::")
        engine = match_technology(parts[-1], catalog) if len(parts) > 3 else None
        service = match_technology(kind.lower(), catalog)
        if engine is None or service is None or engine.name == service.name:
            continue
        found, into = software.get(engine.name), software.get(service.name)
        if found is not None and into is not None and not found.in_environment:
            into.evidence += [e for e in found.evidence if e not in into.evidence]
            into.serves = sorted(set(into.serves) | set(found.serves))
            del software[engine.name]

    for name, entry in sorted(software.items()):
        if entry.in_environment or entry.serves:
            entry.evidence.sort()
            layer.software.append(entry)
        else:
            layer.unconnected.append(name)
    return layer
