"""The closed list of technologies (versioned config): one canonical system software per alias.

An alias is what the repository writes for a technology: a container image (``postgres``), a base image
(``eclipse-temurin``), a client or driver dependency (``psycopg2``), a platform word or a cloud resource
type (``AWS::S3::Bucket``). Matching is case-insensitive on the whole alias; what no entry names is no
system software of the list (the caller keeps it as a fallback and reports its share).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Technology:
    """One entry of the closed list: the canonical name, its kind and the names it goes by."""

    name: str
    kind: str  # database, broker, cache, web server, application server, runtime, transaction monitor, managed service, ...
    aliases: tuple[str, ...] = ()


def image_name(reference: str) -> str:
    """A container image without registry, tag, digest or stage alias: ``public.ecr.aws/docker/library/python:3.12`` -> ``python``."""
    ref = reference.strip().split()[0] if reference.strip() else ""
    ref = ref.split("@", 1)[0]
    if ":" in ref.rsplit("/", 1)[-1]:
        ref = ref.rsplit(":", 1)[0]
    parts = ref.split("/")
    # A registry host (has a dot or a port) and the library namespace are no part of the name
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        parts = parts[1:]
    while len(parts) > 1 and parts[0] in ("docker", "library"):
        parts = parts[1:]
    return "/".join(parts).lower()


def _norm(alias: str) -> str:
    return re.sub(r"\s+", " ", alias.strip().casefold())


def match_technology(alias: str, catalog: tuple[Technology, ...]) -> Technology | None:
    """The catalog entry an alias names (case-insensitive), else None."""
    wanted = _norm(alias)
    return next((t for t in catalog if wanted in {_norm(a) for a in t.aliases} or wanted == _norm(t.name)), None)


def catalog_from_params(entries: Any) -> tuple[Technology, ...]:
    """The closed list from the step params: ``[{"name", "kind", "aliases": [...]}]``."""
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"] and isinstance(e.get("kind"), str) and isinstance(e.get("aliases", []), list) for e in entries
    ):
        raise ValueError("technologies: a list of {name, kind, aliases}")
    # One alias (or name) names one technology: matching would otherwise depend on the list order
    owner: dict[str, int] = {}
    for i, e in enumerate(entries):
        for alias in {_norm(str(a)) for a in [e["name"], *e.get("aliases", [])]}:
            if alias in owner and owner[alias] != i:
                raise ValueError(f"technologies: {alias!r} names both {entries[owner[alias]]['name']} and {e['name']}")
            owner[alias] = i
    return tuple(Technology(name=e["name"], kind=e["kind"], aliases=tuple(str(a) for a in e.get("aliases", []))) for e in entries)
