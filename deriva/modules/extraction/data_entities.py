"""Data entities from structure (no LLM): what a DataObject stands for.

A data entity is a persistent concept of the code, found by its structure:

- aggregate roots: a type that inherits or carries a configured root marker. When a repository
  marks roots, only roots are entities (the other entities are parts of an aggregate);
- ORM entities: a type with an entity annotation, or one that inherits a configured ORM base
  over at most two steps (``LoanApplication -> Base -> DeclarativeBase``);
- shared mainframe records: a copybook record named as a record (``record_pattern``) that at least
  ``min_importers`` programs import (a shared work or communication area is no persistent data);
- DDL tables: a ``CREATE TABLE`` (category ``table``).

Value objects, ids, DTOs, configuration classes and records named with a technical word are out,
each with its reason. One concept is one entity: types with the same cleaned name, also in
different units, are merged. The name comes from the type name without the owning unit's name in
front and without kind suffixes (``PersistenceOrder`` -> ``Order``, ``ACCOUNT-RECORD`` -> ``Account``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from deriva.common.naming import singularize


@dataclass(frozen=True)
class EntityRules:
    """The signals of the DataEntity step (extraction config ``params``); names compare case-insensitively."""

    root_markers: tuple[str, ...] = ()  # Base types or annotations of an aggregate root
    entity_annotations: tuple[str, ...] = ()  # Annotations of a persistent entity
    orm_bases: tuple[str, ...] = ()  # Base types whose (indirect) subtypes are persistent entities
    value_markers: tuple[str, ...] = ()  # Base types or annotations of a value object
    id_markers: tuple[str, ...] = ()  # Base types or annotations of an id type
    dto_bases: tuple[str, ...] = ()  # Base types of data transfer objects
    dto_suffixes: tuple[str, ...] = ()  # Last name words of data transfer objects
    dto_dirs: tuple[str, ...] = ()  # Folders that hold data transfer objects
    config_markers: tuple[str, ...] = ()  # Annotations or base types of configuration classes
    config_suffixes: tuple[str, ...] = ()  # Last name words of configuration classes
    technical_words: tuple[str, ...] = ()  # A name with one of these words (singular) is no business data
    min_importers: int = 3  # Programs that must import a mainframe record
    record_pattern: str = ""  # Full-match pattern of a mainframe record's name (empty: every record)
    name_suffixes: tuple[str, ...] = ()  # Kind words dropped from the end of a name
    table_mentions: bool = False  # Link a DDL table to the code files that name it (NAMED_IN)


@dataclass
class Entity:
    """One data entity: its concept key, name candidates, the signal that made it one, and its types."""

    key: str
    name_candidates: list[tuple[str, str]]
    signal: str
    type_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)  # The DDL table names it merges, as written


@dataclass
class Excluded:
    """A type that looked like data and is no entity, with the reason."""

    type_id: str
    name: str
    reason: str


@dataclass
class EntityResult:
    entities: list[Entity] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)


def _bare(name: str) -> str:
    """An annotation or base type without arguments, generics or qualifiers: ``Entity(name="x")`` -> ``entity``."""
    return re.split(r"[(<\[]", str(name))[0].split(".")[-1].strip().casefold()


def _words(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return [w for w in re.split(r"[\s\-_.]+", spaced) if w]


def _compact(words: list[str]) -> str:
    return "".join(w.casefold() for w in words)


def _flat(name: str) -> str:
    """A name without case or separators, as a generated table name writes its type's name (letters of any script kept)."""
    return re.sub(r"[\W_]", "", name.casefold())


def _cased(word: str) -> str:
    return word[0].upper() + word[1:].lower() if word.isupper() or word.islower() else word


def _is_mainframe(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in (".cpy", ".cbl", ".cob", ".cobol")


def is_root(decorators: list[str], bases: list[str], rules: EntityRules) -> bool:
    """Whether a type's annotations or base types carry a root marker (``rules.root_markers``)."""
    return bool({_bare(x) for x in [*decorators, *bases]} & {m.casefold() for m in rules.root_markers})


def entity_name(type_name: str, unit_name: str, rules: EntityRules, table: bool = False) -> str:
    """The entity's name from its type name: the owning unit's name in front and kind suffixes at the end dropped."""
    words = _words(type_name)
    unit = _words(unit_name) if unit_name else []
    if unit and len(words) > len(unit) and _compact(words[: len(unit)]) == _compact(unit):
        words = words[len(unit) :]
    suffixes = [_words(s) for s in rules.name_suffixes]
    trimmed = True
    while trimmed and len(words) > 1:
        trimmed = False
        for suffix in sorted(suffixes, key=lambda words: len(words), reverse=True):
            if len(words) > len(suffix) and _compact(words[-len(suffix) :]) == _compact(suffix):
                words, trimmed = words[: -len(suffix)], True
                break
    if table and words:
        words[-1] = singularize(words[-1])
    return " ".join(_cased(w) for w in words)


# Line comment markers per file suffix; SQL comments (-- and /* */) are left out in every file
_LINE_COMMENTS = {
    "#": (".py", ".rb", ".sh", ".bash", ".yml", ".yaml", ".pl", ".r", ".toml", ".cfg", ".ini", ".properties"),
    "//": (".java", ".js", ".jsx", ".ts", ".tsx", ".cs", ".go", ".kt", ".scala", ".swift", ".c", ".cpp", ".h", ".php", ".groovy", ".rs"),
}


def _without_comments(path: str, text: str) -> str:
    """The text without comments, so a query in a comment is no use of a table (strings and embedded SQL are kept)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?m)(^|\s)--.*$", r"\1", text)  # an SQL comment (not a decrement such as i--)
    lower = path.lower()
    for marker, suffixes in _LINE_COMMENTS.items():
        if lower.endswith(suffixes):
            # A marker at the start of a line or after whitespace (not inside a URL or a string like "a#b")
            text = re.sub(rf"(?m)(^|\s){re.escape(marker)}.*$", r"\1", text)
    return text


def table_mentions(tables: dict[str, list[str]], files: dict[str, str], own_files: set[str] | None = None) -> dict[str, list[str]]:
    """The files that query a table, per entity key; the files that define it are left out.

    Code reaches a table through its name in a query (SQL strings, embedded SQL), not through an import:
    the table's name as a whole word right after a query keyword (FROM, JOIN, INTO, UPDATE, TABLE), with or
    without a schema in front, case-insensitive. A table named like a common word only counts there.
    """
    found: dict[str, list[str]] = {}
    texts = {path: _without_comments(path, text) for path, text in files.items() if path not in (own_files or set())}
    for key, names in sorted(tables.items()):
        alternatives = "|".join(re.escape(n) for n in sorted(names) if n)
        # A name followed by a dot is a schema (users.orders names orders), not the table
        pattern = re.compile(rf"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:[\w$#@\"`\[\]]+\.)?[\"`\[]?(?:{alternatives})(?![A-Za-z0-9_.])", re.IGNORECASE)
        hits = sorted(path for path, text in texts.items() if pattern.search(text))
        if hits:
            found[key] = hits
    return found


def detect_entities(types: list[dict[str, Any]], importers: dict[str, int], owners: dict[str, str], rules: EntityRules) -> EntityResult:
    """The data entities among ``types``.

    Args:
        types: {"id", "name", "category", "decorators", "path", "bases"} per type definition (bases: names)
        importers: Record file path -> number of programs that import it
        owners: File path -> name of the deployable unit that holds it
        rules: The signals
    """
    lower = lambda values: {v.casefold() for v in values}  # noqa: E731 - a one-line helper
    roots, entity_marks, orm, values, ids = map(lower, (rules.root_markers, rules.entity_annotations, rules.orm_bases, rules.value_markers, rules.id_markers))
    dto_bases, dto_suffixes, dto_dirs = lower(rules.dto_bases), lower(rules.dto_suffixes), lower(rules.dto_dirs)
    configs, config_suffixes, technical = lower(rules.config_markers), lower(rules.config_suffixes), lower(rules.technical_words)

    # A base is known by name only: follow it a second step only when one type has that name (two types named
    # alike could be unrelated, and their bases would mix)
    named: dict[str, list[dict[str, Any]]] = {}
    for t in types:
        named.setdefault(str(t["name"]).casefold(), []).append(t)
    bases_of = {name: {_bare(b) for b in same[0].get("bases") or []} for name, same in named.items() if len(same) == 1}

    def ancestors(t: dict[str, Any]) -> set[str]:
        direct = {_bare(b) for b in t.get("bases") or []}
        return direct | {a for b in direct for a in bases_of.get(b, set())}

    def marks(t: dict[str, Any]) -> set[str]:
        return {_bare(d) for d in t.get("decorators") or [] if ":" not in str(d)} | ancestors(t)

    root_names = {str(t["name"]).casefold() for t in types if marks(t) & roots}
    # ORM bases of the repository itself: types other types name as their base that descend from an ORM base
    referenced = {_bare(b) for t in types for b in t.get("bases") or []}
    orm_names = {str(t["name"]).casefold() for t in types if t.get("bases") and ancestors(t) & orm and str(t["name"]).casefold() in referenced}
    has_roots = bool(root_names)
    result = EntityResult()
    found: dict[str, Entity] = {}

    def exclude(t: dict[str, Any], reason: str) -> None:
        result.excluded.append(Excluded(type_id=str(t["id"]), name=str(t["name"]), reason=reason))
        decided.setdefault(_flat(str(t["name"])), ("excluded", reason))

    def include(t: dict[str, Any], key: str, cleaned: str, signal: str) -> None:
        entity = found.setdefault(key, Entity(key=key, name_candidates=[(cleaned, "type")], signal=signal))
        entity.type_ids = sorted({*entity.type_ids, str(t["id"])})
        entity.paths = sorted({*entity.paths, str(t.get("path") or "")})
        if str(t.get("category") or "") == "table":
            entity.tables = sorted({*entity.tables, str(t["name"])})
        decided.setdefault(_flat(str(t["name"])), ("entity", key))

    # Code types first: a table generated for one (PERSISTENCEORDER for PersistenceOrder) follows its decision
    decided: dict[str, tuple[str, str]] = {}
    for t in sorted(types, key=lambda t: (str(t.get("category") or "") == "table", str(t["id"]))):
        name, path, category = str(t["name"]), str(t.get("path") or ""), str(t.get("category") or "")
        if category == "table" and (follow := decided.get(_flat(name))):
            if follow[0] == "entity":
                include(t, follow[1], found[follow[1]].name_candidates[0][0], found[follow[1]].signal)
            else:
                exclude(t, follow[1])
            continue
        m, words = marks(t), _words(name)
        folders = {part.casefold() for part in PurePosixPath(path).parts[:-1]}
        if category == "table":
            signal = "table"
        elif category == "record" and _is_mainframe(path):
            signal = "shared record"
        elif m & roots:
            signal = "aggregate root"
        elif m & entity_marks or (ancestors(t) & orm and name.casefold() not in orm_names):
            signal = "orm entity"
        elif m & (values | ids | dto_bases):
            signal = ""  # Looks like data: listed with its reason below
        else:
            continue
        cleaned = entity_name(name, owners.get(path, ""), rules, table=signal == "table")
        code = signal not in ("table", "shared record")  # DTO and config rules are about code classes
        if m & ids:
            exclude(t, "id")
        elif m & values or (category == "record" and not _is_mainframe(path) and not m & entity_marks):
            exclude(t, "value object")
        elif code and (m & dto_bases or (words and words[-1].casefold() in dto_suffixes) or folders & dto_dirs):
            exclude(t, "dto")
        elif code and (m & configs or (words and words[-1].casefold() in config_suffixes)):
            exclude(t, "config")
        elif not signal:
            continue
        elif hit := next((w for w in (singularize(x).casefold() for x in _words(cleaned)) if w in technical), None):
            exclude(t, f"technical word: {hit}")
        elif signal == "shared record" and rules.record_pattern and not re.fullmatch(rules.record_pattern, name):
            exclude(t, "not named as a record")
        elif signal == "shared record" and importers.get(path, 0) < rules.min_importers:
            exclude(t, f"used by {importers.get(path, 0)} programs (fewer than {rules.min_importers})")
        elif signal == "orm entity" and has_roots:
            exclude(t, "part of an aggregate")
        else:
            include(t, _compact(_words(cleaned)), cleaned, signal)
    result.entities = sorted(found.values(), key=lambda e: e.key)
    return result
