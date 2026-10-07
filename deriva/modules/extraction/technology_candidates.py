"""Technologies from structure (Technology v2): structure finds the candidates, the LLM classifies them.

The step's input files give two kinds of candidates. A file type can imply a platform (a versioned params
table: a build descriptor implies its language runtime, a compose file the container platform), with no LLM
call. Every other candidate is an item for the LLM: a declared library, a build plugin or profile, a compose
service with its image and the names of its environment variables, a container base image, or the name of an
environment variable (values are never shown). The LLM puts each item into one technology category or none and
names the system the item runs or connects to. Ids, display names, categories and edges come from structure and
the labels, never from generated text.
"""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from deriva.common.naming import contains_name, name_key

from .base import current_timestamp, generate_edge_id, generate_file_node_id
from .external_dependency import parse_requirement_line

CATEGORIES = ("system_software", "service", "infrastructure", "platform", "network", "security")
LABELS = (*CATEGORIES, "none")

CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "name": "technology_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "The item, copied exactly"},
                        "category": {"type": "string", "enum": list(LABELS), "description": "Kind of infrastructure the item runs or connects to, or none"},
                        "system": {"type": "string", "description": "Official name of that infrastructure; empty when the category is none"},
                    },
                    "required": ["item", "category", "system"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class TechnologyItem:
    """One candidate for the LLM: what a file declares, with the kind shown next to it."""

    key: str
    text: str
    kind: str


@dataclass
class Collected:
    """Items by key (first declaration wins the kind), the files that declare each item, and the files per platform."""

    items: dict[str, TechnologyItem] = field(default_factory=dict)
    declared: dict[str, set[str]] = field(default_factory=dict)
    platforms: dict[tuple[str, str], set[str]] = field(default_factory=dict)


# =============================================================================
# What a file declares
# =============================================================================


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _pom_items(content: str) -> list[tuple[str, str]]:
    """Dependencies without test scope, build plugins and build profiles, in document order."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    out = []
    for element in root.iter():
        tag = _local(element.tag)
        fields = {_local(child.tag): (child.text or "").strip() for child in element}
        if tag in ("dependency", "plugin"):
            artifact = fields.get("artifactId", "")
            if not artifact or artifact.startswith("${") or (tag == "dependency" and fields.get("scope") == "test"):
                continue
            kind = "maven library" if tag == "dependency" else "maven build plugin"
            out.append((artifact, f"{kind}, group {fields['groupId']}" if fields.get("groupId") else kind))
        elif tag == "profile" and fields.get("id"):
            out.append((fields["id"], "maven build profile"))
    return out


_GRADLE_DEPENDENCY = re.compile(r"^\s*(\w+)\s*\(?\s*['\"]([^'\":\s]+):([^'\":\s]+)(?::[^'\"]*)?['\"]", re.MULTILINE)


def _gradle_items(content: str) -> list[tuple[str, str]]:
    """Dependencies of every configuration except test configurations."""
    return [(artifact, f"gradle library, group {group}") for configuration, group, artifact in _GRADLE_DEPENDENCY.findall(content) if "test" not in configuration.lower()]


def _json_object(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _package_json_items(content: str) -> list[tuple[str, str]]:
    """Runtime dependencies (development dependencies are build and test tools)."""
    deps = _json_object(content).get("dependencies") or {}
    return [(name, "npm library") for name in deps] if isinstance(deps, dict) else []


def _requirements_items(content: str) -> list[tuple[str, str]]:
    out = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            requirement = parse_requirement_line(line)
            if requirement:
                out.append((requirement["name"], "python library"))
    return out


def _toml(content: str) -> dict:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return {}


def _pyproject_items(content: str) -> list[tuple[str, str]]:
    data = _toml(content)
    names = [r["name"] for r in (parse_requirement_line(d) for d in data.get("project", {}).get("dependencies", [])) if r]
    names += [n for n in data.get("tool", {}).get("poetry", {}).get("dependencies", {}) if n.lower() != "python"]
    return [(n, "python library") for n in names]


def _setup_py_items(content: str) -> list[tuple[str, str]]:
    start = re.search(r"install_requires\s*=\s*\[", content)
    if not start:
        return []
    # The list ends at its matching bracket: extras ("name[extra]") hold brackets of their own
    depth, end = 1, start.end()
    while end < len(content) and depth:
        depth += {"[": 1, "]": -1}.get(content[end], 0)
        end += 1
    requirements = (parse_requirement_line(s) for s in re.findall(r"['\"]([^'\"]+)['\"]", content[start.end() : end]))
    return [(r["name"], "python library") for r in requirements if r]


def _go_mod_items(content: str) -> list[tuple[str, str]]:
    modules, in_block = [], False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("require ("):
            in_block = True
        elif in_block and line == ")":
            in_block = False
        elif in_block and line and not line.startswith("//"):
            modules.append(line.split()[0])
        elif line.startswith("require "):
            modules.append(line.split()[1])
    return [(m, "go module") for m in modules]


def _composer_items(content: str) -> list[tuple[str, str]]:
    require = _json_object(content).get("require") or {}
    names = [n for n in require if n != "php" and not n.startswith(("ext-", "lib-"))] if isinstance(require, dict) else []
    return [(n, "php library") for n in names]


def _gemfile_items(content: str) -> list[tuple[str, str]]:
    return [(name, "ruby gem") for name in re.findall(r"^\s*gem\s+['\"]([^'\"]+)['\"]", content, re.MULTILINE)]


def _cargo_items(content: str) -> list[tuple[str, str]]:
    return [(name, "rust crate") for name in _toml(content).get("dependencies", {})]


def _dockerfile_items(content: str) -> list[tuple[str, str]]:
    """Base images; a FROM that names an earlier build stage is not an image."""
    images, stages = [], set()
    for match in re.finditer(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", content, re.MULTILINE | re.IGNORECASE):
        image, stage = match.group(1), match.group(2)
        if image.lower() not in stages:
            images.append((image, "container image"))
        if stage:
            stages.add(stage.lower())
    return images


def _compose_items(content: str) -> list[tuple[str, str]]:
    """Every service with its image (or that it is built from the repository) and the names of its environment variables."""
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        return []
    out = []
    for name, spec in sorted(services.items(), key=lambda kv: str(kv[0])):
        spec = spec if isinstance(spec, dict) else {}
        parts = ["compose service", f"image {spec['image']}" if spec.get("image") else "built from the repository"]
        environment = spec.get("environment") or {}
        names = sorted(environment) if isinstance(environment, dict) else sorted(str(e).split("=", 1)[0] for e in environment)
        if names:
            parts.append("environment " + " ".join(names))
        out.append((str(name), ", ".join(parts)))
    return out


def _image_items(content: str) -> list[tuple[str, str]]:
    images = re.findall(r"^\s*-?\s*image:\s*['\"]?([^\s'\"]+)", content, re.MULTILINE)
    return [(image, "container image") for image in dict.fromkeys(images)]


def _env_items(content: str) -> list[tuple[str, str]]:
    names = re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", content, re.MULTILINE)
    return [(name, "environment variable") for name in dict.fromkeys(names)]


_BY_TYPE: dict[tuple[str, str], Callable[[str], list[tuple[str, str]]]] = {
    ("infra", "docker"): _dockerfile_items,
    ("infra", "docker-compose"): _compose_items,
    ("infra", "kubernetes"): _image_items,
    ("config", "env"): _env_items,
}
_BY_NAME: dict[str, Callable[[str], list[tuple[str, str]]]] = {
    "pom.xml": _pom_items,
    "package.json": _package_json_items,
    "pyproject.toml": _pyproject_items,
    "setup.py": _setup_py_items,
    "go.mod": _go_mod_items,
    "composer.json": _composer_items,
    "gemfile": _gemfile_items,
    "cargo.toml": _cargo_items,
}


def items_from_file(path: str, content: str, file_type: str, subtype: str | None) -> list[tuple[str, str]]:
    """(text, kind) of every item a file declares; files of other kinds declare nothing."""
    name = Path(path).name.lower()
    parser = _BY_TYPE.get((file_type, subtype or "")) or _BY_NAME.get(name)
    if parser is None and name.endswith(".txt") and "requirements" in name:
        parser = _requirements_items
    if parser is None and name.endswith((".gradle", ".gradle.kts")):
        parser = _gradle_items
    return parser(content) if parser else []


_COMPOSE_IMAGE = re.compile(r"image (\S+?)(?:,|$)")


def own_unit_names(files: list[dict[str, Any]], file_types: frozenset[str], subtypes: frozenset[str]) -> frozenset[str]:
    """Name keys of the repository's own modules: the directories that directly hold a file of one of the types or
    subtypes (a build, dependency or container file). The repository root is no module of its own."""
    names = set()
    for f in files:
        parent = PurePosixPath(str(f.get("path", "")).replace(chr(92), "/")).parent
        if parent.name and (f.get("file_type") in file_types or (f.get("subtype") or "") in subtypes) and (key := name_key(parent.name)):
            names.add(key)
    return frozenset(names)


def _own_module_service(text: str, kind: str, own_units: frozenset[str]) -> bool:
    """A compose service named like one of the repository's own modules, or running an image tagged like one."""
    if not own_units or not kind.startswith("compose service"):
        return False
    if name_key(text) in own_units:
        return True
    image = _COMPOSE_IMAGE.search(kind)
    reference = image.group(1).split("@", 1)[0] if image else ""  # a digest is no tag
    return ":" in reference and name_key(reference.rsplit(":", 1)[1]) in own_units


def _names_repository(text: str, kind: str, repository_name: str) -> bool:
    """An item named after the repository, or a compose service running an image named after it: the software itself."""
    if not repository_name:
        return False
    image = _COMPOSE_IMAGE.search(kind) if kind.startswith("compose service") else None
    return contains_name(text, repository_name) or bool(image and contains_name(image.group(1), repository_name))


def item_key(text: str, kind: str) -> str:
    """One item per kind and text, whatever details the kind shows."""
    return f"{kind.split(',')[0]}::{text.casefold()}"


def technology_node_id(repo_name: str, tech_name: str) -> str:
    """Graph id of a technology: one id for every spelling of its name (canonical name key)."""
    return f"tech::{repo_name}::{name_key(tech_name)}"


def collect(files: list[dict[str, Any]], platforms: list[dict[str, str]], own_units: frozenset[str] = frozenset(), repository_name: str = "") -> Collected:
    """The items the files declare and the platforms their types imply (platforms: the step's params table).

    A compose service that is one of the repository's own modules (``own_units``, name keys) is no item, and with
    ``repository_name`` neither is an item named after the repository (an image, a library, a service running such
    an image): it is or runs the software itself, not a technology it uses.
    """
    table = {(p["file_type"], p["subtype"]): (p["name"], p["category"]) for p in platforms}
    collected = Collected()
    for f in files:
        platform = table.get((f["file_type"], f.get("subtype") or ""))
        if platform:
            collected.platforms.setdefault(platform, set()).add(f["path"])
        for text, kind in items_from_file(f["path"], f["content"], f["file_type"], f.get("subtype")):
            if _own_module_service(text, kind, own_units) or _names_repository(text, kind, repository_name):
                continue
            key = item_key(text, kind)
            collected.items.setdefault(key, TechnologyItem(key, text, kind))
            collected.declared.setdefault(key, set()).add(f["path"])
    return collected


# =============================================================================
# Classification
# =============================================================================


def build_classification_prompt(instruction: str, batch: list[TechnologyItem]) -> str:
    """The configured instruction, then every item with its kind."""
    lines = [instruction.strip(), "", "Items:"]
    lines.extend(f'{i}. "{item.text}" ({item.kind})' for i, item in enumerate(batch, 1))
    return "\n".join(lines) + "\n"


def parse_labels(content: str, batch: list[TechnologyItem]) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Labels by item key. An answer names its item by the text or by the whole line (kind included)."""
    lookup: dict[str, str] = {}
    for item in batch:
        for form in (item.text, f"{item.text} ({item.kind})"):
            lookup.setdefault(form.casefold(), item.key)
    labels: dict[str, dict[str, str]] = {}
    issues: dict[str, list[str]] = {"unmatched": [], "duplicates": [], "missing": []}
    for answer in json.loads(content).get("items", []):
        text, category = str(answer.get("item", "")), answer.get("category")
        if category not in LABELS:
            raise ValueError(f"Unknown category {category!r} for item {text!r}")
        key = lookup.get(text.replace('"', "").strip().casefold())
        if key is None:
            issues["unmatched"].append(text)
        elif key in labels:
            issues["duplicates"].append(text)
        else:
            labels[key] = {"category": category, "system": str(answer.get("system") or "").strip()}
    issues["missing"] = [item.text for item in batch if item.key not in labels]
    return labels, issues


# =============================================================================
# Nodes and edges
# =============================================================================


def technology_nodes_and_edges(
    labels: dict[str, dict[str, str]],
    collected: Collected,
    repo_name: str,
    confidence: float,
    existing: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A node per platform and per named system, a CONFIGURES edge from every file that implies or declares it.

    Ids come from the canonical name key; a platform or system whose key names a technology that exists
    before the step (``existing``: name key -> node id) gets edges to that node and no new one. A system's
    display name is the answer of its first item in key order, its category the most frequent answer (ties
    by name). Platforms have the method and edge route "structural", systems "llm" (an LLM label decided them).
    """
    now = current_timestamp()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: dict[str, str] = dict(existing)
    linked: set[tuple[str, str]] = set()

    def add_node(key: str, name: str, category: str, origin: str, method: str) -> str:
        if key not in node_ids:
            node_ids[key] = technology_node_id(repo_name, name)
            properties = {"techName": name, "techCategory": category, "description": "", "version": None, "originSource": origin, "confidence": confidence, "extracted_at": now}
            nodes.append({"node_id": node_ids[key], "label": "Technology", "method": method, "properties": properties})
        return node_ids[key]

    def add_edges(paths: set[str], node_id: str, route: str) -> None:
        for path in sorted(paths):
            file_id = generate_file_node_id(repo_name, path)
            if (file_id, node_id) not in linked:
                linked.add((file_id, node_id))
                edge_id = generate_edge_id(file_id, node_id, "CONFIGURES")
                edges.append(
                    {"edge_id": edge_id, "from_node_id": file_id, "to_node_id": node_id, "relationship_type": "CONFIGURES", "properties": {"route": route, "created_at": now}}
                )

    for (name, category), paths in sorted(collected.platforms.items()):
        add_edges(paths, add_node(name_key(name), name, category, sorted(paths)[0], "structural"), "structural")

    systems: dict[str, dict[str, Any]] = {}
    for key in sorted(labels):
        label = labels[key]
        system_key = name_key(label["system"])
        if label["category"] == "none" or not system_key:
            continue
        system = systems.setdefault(system_key, {"name": label["system"], "categories": Counter(), "paths": set()})
        system["categories"][label["category"]] += 1
        system["paths"] |= collected.declared.get(key, set())
    for system_key, system in sorted(systems.items()):
        category = sorted(system["categories"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        node_id = add_node(system_key, system["name"], category, sorted(system["paths"])[0] if system["paths"] else "", "llm")
        add_edges(system["paths"], node_id, "llm")
    return nodes, edges
