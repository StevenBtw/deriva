"""Baseline B1: an LLM generates a whole ArchiMate model from raw repository material in one go.

Following Nast et al. (BIS 2026), one template-driven generation produces the complete model; the template is a typed
output with closed enums for the element and relationship types. The answer is validated (duplicate ids, unknown
endpoints, relationships the ArchiMate 3.2 relationship table does not allow) and repaired at most ``max_repairs``
times with the error list; after that the invalid relationships (and duplicate elements) are dropped. The repair loop
is our own composition, not taken from a published design. k = 1: no sampling, no voting.

The input is raw repository material within a fixed character budget, the same for every model, selected without
Deriva's graph: the README, the directory tree, then manifest, build and deployment files (in path order) and source
files (the largest first, tests left out) in turn, so both kinds are represented. The prompt text lives in the ``BaselineB1`` config row (phase
``baseline``, never run by the pipeline); this module holds only structure.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from deriva.adapters.archimate.models import Element, Relationship, validate_relationship_rule
from deriva.common.json_utils import extract_json_from_response
from deriva.common.naming import name_key
from deriva.modules.derivation.base import element_identifier
from deriva.modules.extraction.classification import classify_files

SCHEMA: dict[str, Any] = {"name": "archimate_model_generation"}
CONFIG_STEP = "BaselineB1"  # the config row with the instruction and params (phase baseline)


@dataclass(frozen=True)
class B1Params:
    """The ``BaselineB1`` config row's params (versioned)."""

    budget_chars: int = 120_000
    readme_chars: int = 6_000
    tree_depth: int = 4
    tree_entries: int = 400
    per_file_chars: int = 6_000
    max_repairs: int = 2
    manifest_patterns: tuple[str, ...] = (
        "package.json", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "pyproject.toml", "requirements*.txt",
        "setup.py", "go.mod", "cargo.toml", "*.csproj", "*.sln", "makefile", "dockerfile", "dockerfile.*", "*.dockerfile",
        "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml", "cdk.json", "*.tf", "serverless.yml",
    )  # fmt: skip
    source_extensions: tuple[str, ...] = (
        ".java", ".py", ".js", ".jsx", ".ts", ".tsx", ".cs", ".go", ".rb", ".php", ".kt", ".scala", ".cbl", ".cob", ".jcl", ".pl",
    )  # fmt: skip
    test_markers: tuple[str, ...] = ("test", "tests", "spec", "specs", "__tests__", "testing")
    excluded_directories: tuple[str, ...] = (".git", "node_modules", "target", "build", "dist", "vendor", ".venv", "venv", "__pycache__")

    @classmethod
    def from_params(cls, params: dict[str, Any] | None, excluded: list[str] | None = None) -> B1Params:
        values = dict(params or {})
        for key in ("manifest_patterns", "source_extensions", "test_markers"):
            if key in values:
                values[key] = tuple(values[key])
        if excluded:
            values["excluded_directories"] = tuple(excluded)
        return cls(**{k: v for k, v in values.items() if k in cls.__dataclass_fields__})


def _files(root: Path, params: B1Params) -> list[tuple[str, int]]:
    """(repository-relative path, size) of every file outside the excluded directories, in path order."""
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in params.excluded_directories for part in PurePosixPath(rel).parts[:-1]):
            continue
        found.append((rel, path.stat().st_size))
    return sorted(found)


def _is_test(rel: str, params: B1Params) -> bool:
    parts = [p.lower() for p in PurePosixPath(rel).parts]
    stem = PurePosixPath(rel).stem.lower()
    return any(p in params.test_markers for p in parts[:-1]) or stem.startswith("test") or stem.endswith(("test", "tests", "spec"))


def _read(root: Path, rel: str, limit: int) -> str:
    try:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n[... truncated]"


def repository_material(root: Path, params: B1Params, registry: list[dict[str, str]] | None = None) -> tuple[str, dict[str, Any]]:
    """The input text (README, tree, manifests, sources by size) within the budget, and what it holds.

    Files the file-type registry excludes (reference models, model files, backups) are left out everywhere, the
    directory tree included, as the pipeline leaves them out of extraction.
    """
    files = _files(root, params)
    excluded: set[str] = set()
    if registry:
        classified = classify_files([rel for rel, _ in files], registry)["classified"]
        excluded = {c["path"] for c in classified if c["file_type"] == "exclude"}
        files = [(rel, size) for rel, size in files if rel not in excluded]
    parts: list[str] = []
    manifest: dict[str, Any] = {"readme": None, "manifests": [], "sources": [], "tree_entries": 0, "excluded": len(excluded)}
    used = 0

    def add(text: str) -> bool:
        nonlocal used
        if used + len(text) > params.budget_chars:
            return False
        parts.append(text)
        used += len(text)
        return True

    readme = next((rel for rel, _ in files if PurePosixPath(rel).parent == PurePosixPath(".") and PurePosixPath(rel).name.lower().startswith("readme")), None)
    if readme and add(f"## README ({readme})\n{_read(root, readme, params.readme_chars)}\n\n"):
        manifest["readme"] = readme
    entries: set[str] = set()
    for rel, _ in files:
        segments = PurePosixPath(rel).parts
        for depth in range(1, min(params.tree_depth, len(segments)) + 1):
            entries.add("/".join(segments[:depth]) + ("/" if depth < len(segments) else ""))
    tree = sorted(entries)
    shown = tree[: params.tree_entries]
    if add("## Directory tree\n" + "\n".join(shown) + ("\n[...]" if len(tree) > len(shown) else "") + "\n\n"):
        manifest["tree_entries"] = len(shown)
    manifests = [rel for rel, _ in files if any(fnmatch.fnmatchcase(PurePosixPath(rel).name.lower(), p) for p in params.manifest_patterns)]
    sources = [
        rel
        for rel, _ in sorted(
            ((rel, size) for rel, size in files if rel.lower().endswith(params.source_extensions) and not _is_test(rel, params)),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    # Manifests (in path order) and sources (largest first) in turn, so many build files cannot crowd out the code;
    # a file that no longer fits is skipped
    for k in range(max(len(manifests), len(sources))):
        for kind, rel, heading in (("manifests", manifests[k] if k < len(manifests) else None, "File"), ("sources", sources[k] if k < len(sources) else None, "Source")):
            if rel is not None and add(f"## {heading} {rel}\n{_read(root, rel, params.per_file_chars)}\n\n"):
                manifest[kind].append(rel)
    manifest["chars"] = used
    return "".join(parts), manifest


def build_prompt(instruction: str, material: str) -> str:
    """The generation prompt: the configured instruction, the material and the output contract."""
    return f"""{instruction}

# Repository material
{material}
# Output
Return {{"elements": [{{"id", "type", "name"}}], "relationships": [{{"source", "target", "type"}}]}}: every element once, relationships between element ids."""


def build_repair_prompt(prompt: str, answer: dict[str, Any], errors: list[str]) -> str:
    """The repair prompt: the original prompt, the previous answer and its errors."""
    listed = "\n".join(f"- {e}" for e in errors)
    return f"""{prompt}

## Previous answer
```json
{json.dumps(answer, sort_keys=True)}
```

## Errors
{listed}

Return the complete corrected model."""


def validate(model: dict[str, Any]) -> list[str]:
    """Duplicate ids, unknown endpoints and relationships the ArchiMate relationship table does not allow."""
    errors: list[str] = []
    types: dict[str, str] = {}
    for e in model.get("elements", []):
        if e["id"] in types:
            errors.append(f"duplicate id {e['id']}")
            continue
        types[e["id"]] = e["type"]
    for r in model.get("relationships", []):
        for end in ("source", "target"):
            if r[end] not in types:
                errors.append(f"relationship {r['source']} -{r['type']}-> {r['target']}: unknown {end} {r[end]}")
        if r["source"] in types and r["target"] in types:
            ok, reason = validate_relationship_rule(types[r["source"]], r["type"], types[r["target"]])
            if not ok:
                errors.append(f"relationship {r['source']} -{r['type']}-> {r['target']}: {reason}")
    return errors


def _parse(response: Any) -> dict[str, Any] | None:
    content = getattr(response, "content", None)
    if content is None and response is not None and hasattr(response, "model_dump"):
        return response.model_dump()
    try:
        data = json.loads(extract_json_from_response(str(content or "")))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "elements": [e for e in data.get("elements", []) if isinstance(e, dict) and {"id", "type", "name"} <= set(e)],
        "relationships": [r for r in data.get("relationships", []) if isinstance(r, dict) and {"source", "target", "type"} <= set(r)],
    }


def _cleaned(model: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """The model without duplicate elements and invalid relationships (dropped counts)."""
    elements, seen = [], set()
    for e in model.get("elements", []):
        if e["id"] not in seen:
            seen.add(e["id"])
            elements.append(e)
    kept = {"elements": elements, "relationships": []}
    for r in model.get("relationships", []):
        if not validate({"elements": elements, "relationships": [r]}):
            kept["relationships"].append(r)
    return kept, len(model.get("elements", [])) - len(elements), len(model.get("relationships", [])) - len(kept["relationships"])


def generate(llm_query_fn: Callable[..., Any], instruction: str, material: str, params: B1Params) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate, validate and repair (at most ``max_repairs`` times); the cleaned model and a report."""
    prompt = build_prompt(instruction, material)
    report = {"calls": 0, "repairs": 0, "errors_left": 0, "dropped_relationships": 0, "dropped_elements": 0, "parse_failures": 0}
    model: dict[str, Any] = {"elements": [], "relationships": []}
    current = prompt
    for attempt in range(params.max_repairs + 1):
        report["calls"] += 1
        parsed = _parse(llm_query_fn(current, SCHEMA))
        if parsed is None:
            report["parse_failures"] += 1
            errors = ["the answer is no readable JSON model"]
        else:
            model = parsed
            errors = validate(model)
        if not errors or attempt == params.max_repairs:
            report["errors_left"] = len(errors)
            break
        report["repairs"] += 1
        current = build_repair_prompt(prompt, model, errors)
    model, report["dropped_elements"], report["dropped_relationships"] = _cleaned(model)
    return model, report


def element_id(element_type: str, name: str) -> str:
    """B1 has no source nodes: its identity is the type and the canonical name key."""
    return element_identifier(element_type, f"b1::{name_key(name) or 'unnamed'}")


def to_archimate(model: dict[str, Any]) -> tuple[list[Element], list[Relationship]]:
    """ArchiMate elements and relationships (ids from type and name; a repeated identity is kept once)."""
    ids: dict[str, str] = {}
    elements: list[Element] = []
    for e in model.get("elements", []):
        identifier = element_id(e["type"], e["name"])
        ids[e["id"]] = identifier
        if all(x.identifier != identifier for x in elements):
            elements.append(Element(name=e["name"], element_type=e["type"], identifier=identifier, properties={"source": None, "derived_from": "llm_b1"}))
    relationships: list[Relationship] = []
    seen: set[tuple[str, str, str]] = set()
    for r in model.get("relationships", []):
        key = (ids[r["source"]], r["type"], ids[r["target"]])
        if key in seen or key[0] == key[2]:
            continue
        seen.add(key)
        identifier = f"rel_b1_{r['type'].lower()}_{key[0]}_{key[2]}"
        relationships.append(Relationship(source=key[0], target=key[2], relationship_type=r["type"], identifier=identifier, properties={"derived_from": "llm_b1"}))
    return elements, relationships


@dataclass
class B1Result:
    elements: list[Element] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    material: dict[str, Any] = field(default_factory=dict)
