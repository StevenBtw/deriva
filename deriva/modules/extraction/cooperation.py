"""Cooperation between deployable units (no LLM): which unit uses which, and which sends messages to which.

Units are deployed on their own and talk over the network, so the lines come mostly from configuration:

- endpoint: a URL in a unit's configuration (properties, YAML, .env, its compose environment) whose host is
  another unit's service name, or whose loopback port is another unit's port;
- messaging: a destination (queue/topic name) that one unit's code sends to and another unit's code listens
  on; the destination is resolved through each unit's own configuration (``${key}`` placeholders, keys);
- service catalog: a constant whose string value is another unit's folder name (a registry enum), referenced
  as ``Type.CONSTANT`` in a unit's code;
- gateway route: a proxy route (nginx ``location`` -> ``proxy_pass`` upstream) to another unit, whose path a
  unit's code calls;
- code edge: a code edge between files that only one unit each holds (shared files are no dependency).

A use is ``CONSUMES`` (consumer -> provider, with the channel of the provider's interface it reaches);
a message flow is ``SENDS_TO`` (sender -> listener). A unit never uses itself.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from deriva.modules.extraction.deployments import _Units

_URL = re.compile(r"\b(https?|wss?|grpc)://([A-Za-z0-9_.-]+)(?::(\d+))?")
_LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0"}
_CHANNEL = {"http": "rest", "https": "rest", "ws": "rest", "wss": "rest", "grpc": "rpc"}
_PORT_LINES = (re.compile(r"(?im)^\s*server\.port\s*[=:]\s*(\d+)"), re.compile(r"(?im)^\s*EXPOSE\s+(\d+)"), re.compile(r"(?m)^\s*port:\s*(\d+)\s*$"))


@dataclass(frozen=True)
class CooperationRules:
    """The signals of the Cooperation step (extraction config ``params``)."""

    config_files: tuple[str, ...] = ("*.properties", "application*.yml", "application*.yaml", ".env", ".env.*", "*.env", "config*.json")
    excluded_dirs: tuple[str, ...] = ("test", "tests")
    destination_key: str = r"(?i).*(queue|topic|destination)(name)?$"  # The last segment of a configuration key
    send_markers: tuple[str, ...] = ()
    listen_markers: tuple[str, ...] = ()
    gateway_files: tuple[str, ...] = ("nginx*.conf", "*.nginx")
    code_files: tuple[str, ...] = ("*.java", "*.kt", "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.cs")


@dataclass(frozen=True)
class Link:
    relation: str  # CONSUMES (consumer -> provider) or SENDS_TO (sender -> listener)
    source: str
    target: str
    channel: str  # rest, rpc, messaging, code
    evidence: str  # endpoint, messaging, service catalog, gateway route, code edge
    detail: str


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    name = PurePosixPath(path).name.lower()
    return any(fnmatch.fnmatchcase(name, p.lower()) for p in patterns)


def _excluded(path: str, rules: CooperationRules) -> bool:
    return any(part.lower() in rules.excluded_dirs for part in PurePosixPath(path).parts[:-1])


def _config_pairs(path: str, text: str) -> list[tuple[str, str]]:
    """(key, value) pairs of a configuration file: properties/.env lines, flattened JSON, simple YAML lines."""
    if path.lower().endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return []
        pairs: list[tuple[str, str]] = []

        def walk(node: Any, prefix: str) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{prefix}.{k}" if prefix else str(k))
            elif isinstance(node, str | int | float):
                pairs.append((prefix, str(node)))

        walk(data, "")
        return pairs
    found = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z0-9_.\-]+)\s*[=:]\s*[\"']?([^\"'#\s]*)", line)
        if m and m.group(2):
            found.append((m.group(1), m.group(2)))
    return found


def detect_links(
    files: dict[str, str],
    units: list[dict[str, Any]],
    services: list[dict[str, Any]],
    rules: CooperationRules,
    code_edges: list[tuple[str, str]],
) -> list[Link]:
    """The links between units.

    Args:
        files: Path -> text of the configuration, gateway, container and code files
        units: {"id", "path", "name", "members"} of the deployable units
        services: {"name", "unit", "environment", "ports"} of the primary environment's services
        rules: The signals
        code_edges: (file, file) code edges between files (imports, calls)
    """
    lookup = _Units(units)
    by_service = {str(s["name"]): s["unit"] for s in services if s.get("unit")}
    ports: dict[int, set[str]] = {}
    for s in services:
        for port in s.get("ports") or []:
            if s.get("unit"):
                ports.setdefault(int(port), set()).add(s["unit"])
    for path, text in files.items():
        if _excluded(path, rules):
            continue
        holders = lookup.holders(path)
        if len(holders) == 1 and (_matches(path, rules.config_files) or PurePosixPath(path).name.lower().startswith("dockerfile")):
            for pattern in _PORT_LINES:
                for m in pattern.finditer(text):
                    ports.setdefault(int(m.group(1)), set()).add(holders[0])
    unique_port = {p: next(iter(us)) for p, us in ports.items() if len(us) == 1}
    links: dict[tuple[str, str, str], Link] = {}

    def add(relation: str, source: str | None, target: str | None, channel: str, evidence: str, detail: str) -> None:
        if source and target and source != target:
            links.setdefault((relation, source, target), Link(relation, source, target, channel, evidence, detail))

    def provider(host: str, port: str | None) -> str | None:
        if host in by_service:
            return by_service[host]
        if host in _LOOPBACK and port:
            return unique_port.get(int(port))
        return None

    # (1) Endpoint configuration: the unit's own files, then its compose environment
    for path, text in sorted(files.items()):
        if _excluded(path, rules) or not _matches(path, rules.config_files):
            continue
        for consumer in lookup.holders(path):
            for _, value in _config_pairs(path, text):
                for m in _URL.finditer(value):
                    add("CONSUMES", consumer, provider(m.group(2), m.group(3)), _CHANNEL[m.group(1)], "endpoint", f"{path}: {m.group(0)}")
    for s in services:
        for value in (s.get("environment") or {}).values():
            for m in _URL.finditer(str(value)):
                add("CONSUMES", s.get("unit"), provider(m.group(2), m.group(3)), _CHANNEL[m.group(1)], "endpoint", f"compose {s['name']}: {m.group(0)}")

    # (4) Messaging: destinations from each unit's configuration, roles from its code
    destination_key = re.compile(rules.destination_key)
    keys_of: dict[str, dict[str, str]] = {}  # unit -> configuration key -> destination
    json_keys: set[str] = set()  # keys from JSON configuration: code reads them as fields (".queueName")
    for path, text in files.items():
        if _excluded(path, rules) or not _matches(path, rules.config_files):
            continue
        for unit in lookup.holders(path):
            for key, value in _config_pairs(path, text):
                if destination_key.fullmatch(key.rsplit(".", 1)[-1]):
                    keys_of.setdefault(unit, {})[key] = value
                    if path.lower().endswith(".json"):
                        json_keys.add(key)
    senders: dict[str, set[str]] = {}
    listeners: dict[str, set[str]] = {}
    for path, text in files.items():
        if _excluded(path, rules) or not _matches(path, rules.code_files):
            continue
        for unit in lookup.holders(path):
            for key, destination in keys_of.get(unit, {}).items():
                field_read = key in json_keys and re.search(rf"\.{re.escape(key.rsplit('.', 1)[-1])}\b", text) is not None
                if key not in text and destination not in text and not field_read:
                    continue
                if any(marker in text for marker in rules.send_markers):
                    senders.setdefault(destination, set()).add(unit)
                if any(marker in text for marker in rules.listen_markers):
                    listeners.setdefault(destination, set()).add(unit)
    for destination in sorted(senders):
        for sender in sorted(senders[destination]):
            for listener in sorted(listeners.get(destination, ())):
                add("SENDS_TO", sender, listener, "messaging", "messaging", destination)

    # (3) Service catalog: constants whose value is a unit's folder name, referenced as Type.CONSTANT
    folders = {PurePosixPath(str(u["path"])).name: str(u["id"]) for u in units}
    catalog: dict[str, str] = {}  # "Type.CONSTANT" -> unit
    for path, text in files.items():
        if not _matches(path, rules.code_files):
            continue
        declared = re.search(r"\b(?:enum|class|interface|object)\s+(\w+)", text)
        if not declared:
            continue
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]*)\s*(?:\(\s*|=\s*)[\"']([^\"']+)[\"']", text):
            if m.group(2) in folders:
                catalog[f"{declared.group(1)}.{m.group(1)}"] = folders[m.group(2)]
    for path, text in sorted(files.items()):
        if _excluded(path, rules) or not _matches(path, rules.code_files):
            continue
        for consumer in lookup.holders(path):
            for reference, unit in sorted(catalog.items()):
                if re.search(rf"\b{re.escape(reference)}\b", text):
                    add("CONSUMES", consumer, unit, "rest", "service catalog", f"{path}: {reference}")

    # (2) Gateway routes: location prefix -> upstream -> unit; a unit's code that calls the path
    routes: dict[str, str] = {}
    for path, text in files.items():
        if not _matches(path, rules.gateway_files):
            continue
        upstreams = {m.group(1): m.group(2) for m in re.finditer(r"upstream\s+([\w-]+)\s*\{[^}]*?server\s+([\w.-]+)", text)}
        for m in re.finditer(r"location\s+[=~^]*\s*(/[^\s{]*)\s*\{[^}]*?proxy_pass\s+https?://([\w.-]+)", text):
            host = upstreams.get(m.group(2), m.group(2))
            # A catch-all route ("/") is no route to one unit
            if host in by_service and m.group(1).strip("/"):
                routes[m.group(1).rstrip("/")] = by_service[host]
    if routes:
        # The base all routes share ("/api/v1"), which code may keep apart from the route paths
        parts = [PurePosixPath(p).parts for p in routes]
        common = [segment[0] for segment in zip(*parts, strict=False) if len(set(segment)) == 1]
        base = "/" + "/".join(common[1:]) if len(common) > 1 else ""
        base = base if all(p != base for p in routes) else str(PurePosixPath(base).parent)
        for path, text in sorted(files.items()):
            if _excluded(path, rules) or not _matches(path, rules.code_files):
                continue
            with_base = bool(base) and re.search(rf"[\"'`]{re.escape(base)}/?[\"'`]", text) is not None
            for consumer in lookup.holders(path):
                for prefix, unit in sorted(routes.items()):
                    rest = prefix[len(base) :] if base else prefix
                    if not rest.strip("/"):
                        continue
                    if re.search(rf"[\"'`]{re.escape(prefix)}(?![\w-])", text) or (with_base and re.search(rf"[\"'`]{re.escape(rest)}(?![\w-])", text)):
                        add("CONSUMES", consumer, unit, "rest", "gateway route", f"{path}: {prefix}")

    # (5) Code edges between files that only one unit each holds
    owners: dict[str, list[str]] = {}
    for u in units:
        for member in u.get("members") or []:
            owners.setdefault(member, []).append(str(u["id"]))
    for a, b in sorted(code_edges):
        if len(owners.get(a, [])) == 1 and len(owners.get(b, [])) == 1:
            add("CONSUMES", owners[a][0], owners[b][0], "code", "code edge", f"{a} -> {b}")

    return sorted(links.values(), key=lambda link: (link.relation, link.source, link.target))
