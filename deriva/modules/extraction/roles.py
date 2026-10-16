"""Actors and roles from structure (no LLM).

- A role is a role constant in an authorization check (versioned markers such as ``require_role(...)``,
  ``hasRole(...)``, ``@RolesAllowed(...)``), named in words; generic roles (admin, user) are left out. It is
  assigned to the lifecycles whose states the units with those checks reach.
- An actor is a business concept classified as an actor or role (the BusinessConcept step) that the README in a
  Web UI component's folder names: a person using that UI. It is assigned to the lifecycles of the units the UI
  component uses (gap 1 CONSUMES). Generic words (user, client) are left out.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class RoleRules:
    markers: tuple[str, ...] = ()  # Patterns whose first group holds the role constants of an authorization check
    generic_roles: tuple[str, ...] = ()  # Role words left out (admin, user, ...)
    generic_actors: tuple[str, ...] = ()  # Actor names left out (user, client, ...)


@dataclass
class Role:
    name: str
    kind: str  # role (authorization) or actor (documentation)
    source: str  # The role constant or the business concept id
    lifecycles: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)


def _name(constant: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\s-]+", constant.strip()) if w)


def detect_roles(
    files: dict[str, str],
    concepts: list[dict[str, Any]],
    units: list[dict[str, Any]],
    lifecycles: dict[str, list[str]],
    consumes: list[tuple[str, str]],
    rules: RoleRules,
) -> list[Role]:
    """The roles and actors.

    Args:
        files: Path -> text of the code files
        concepts: {"id", "name", "files"} of the business concepts classified actor or role
        units: {"id", "path", "web"} of the deployable units (``web``: the unit has a Web UI)
        lifecycles: Lifecycle id -> the units that reach its states
        consumes: (consumer unit, provider unit) lines
        rules: The signals
    """
    by_depth = sorted(units, key=lambda u: -len(str(u["path"])))

    def unit_of(path: str) -> str | None:
        return next((str(u["id"]) for u in by_depth if path.startswith(str(u["path"]) + "/")), None)

    def lifecycles_of(unit_ids: set[str]) -> list[str]:
        return sorted(life for life, reached in lifecycles.items() if set(reached) & unit_ids)

    generic_roles = {g.casefold() for g in rules.generic_roles}
    found: dict[str, set[str]] = defaultdict(set)  # role constant -> units
    for path, text in sorted(files.items()):
        unit = unit_of(path)
        for marker in rules.markers:
            for args in re.findall(marker, text):
                for constant in re.findall(r"[\"']([A-Za-z][\w-]*)[\"']", args):
                    if constant.casefold().removeprefix("role_") not in generic_roles and unit:
                        found[constant.removeprefix("ROLE_")].add(unit)
    roles = [Role(name=_name(c), kind="role", source=c, units=sorted(u), lifecycles=lifecycles_of(u)) for c, u in sorted(found.items())]

    web_folders = {str(u["path"]): str(u["id"]) for u in units if u.get("web")}
    uses: dict[str, set[str]] = defaultdict(set)
    for consumer, provider in consumes:
        uses[consumer].add(provider)
    generic_actors = {g.casefold() for g in rules.generic_actors}
    for concept in sorted(concepts, key=lambda c: c["id"]):
        if concept["name"].casefold() in generic_actors:
            continue
        readmes = [f for f in concept.get("files") or [] if PurePosixPath(f).name.casefold().startswith("readme") and str(PurePosixPath(f).parent) in web_folders]
        ui_units = {web_folders[str(PurePosixPath(f).parent)] for f in readmes}
        if not ui_units:
            continue
        reached = ui_units | {p for u in ui_units for p in uses.get(u, set())}
        roles.append(Role(name=concept["name"], kind="actor", source=concept["id"], units=sorted(ui_units), lifecycles=lifecycles_of(reached)))
    return roles
