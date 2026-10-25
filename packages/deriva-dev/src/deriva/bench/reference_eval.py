"""Evaluation of exported models against a development reference model (``workspace/goldens/dev/<repo>.json``).

Deterministic, no LLM. A model element maps to the reference element of its type whose name or alias has
the same name key, else whose lineage holds its source or identifier (structural ids: units, entities,
environments); a model element maps to at most one reference element, a reference element may be covered
by several model elements (a split: the model is finer than the reference). A relationship matches when
its ends map to the reference ends and its type and direction agree; a model relationship with an end that
maps to nothing cannot be judged (unassessable). A chain counts its steps that exist in the model.
Reference elements marked ``optional`` (they depend on an open decision) stay outside recall.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deriva.adapters.archimate.models import match_kind, types_match
from deriva.common.naming import name_key


@dataclass(frozen=True)
class RefElement:
    key: str
    types: tuple[str, ...]  # The first type is the one it is reported under
    name: str
    aliases: tuple[str, ...] = ()
    lineage: frozenset[str] = frozenset()
    optional: bool = False
    levels: frozenset[str] = frozenset({"enterprise"})  # The abstraction levels it belongs to


@dataclass(frozen=True)
class RefRelationship:
    source: str
    target: str
    type: str
    kind: str
    optional: bool = False
    levels: frozenset[str] = frozenset({"enterprise"})


@dataclass(frozen=True)
class Chain:
    name: str
    steps: tuple[tuple[str, str, str, bool], ...]  # (from key, relationship type, to key, also counts reversed)


@dataclass
class Reference:
    repository: str
    elements: list[RefElement] = field(default_factory=list)
    relationships: list[RefRelationship] = field(default_factory=list)
    chains: list[Chain] = field(default_factory=list)
    tagged: bool = False  # Whether any element or relationship names its levels; untagged, all count as enterprise


def parse_reference(data: dict[str, Any]) -> Reference:
    """A reference model from its JSON form; every relationship and chain end must be an element key."""
    elements = [
        RefElement(
            key=e["key"],
            types=tuple(e["type"]) if isinstance(e["type"], list) else (e["type"],),
            name=e["name"],
            aliases=tuple(e.get("aliases", [])),
            lineage=frozenset(e.get("lineage", [])),
            optional=bool(e.get("optional", False)),
            levels=_levels_of(e),
        )
        for e in data["elements"]
    ]
    keys = {e.key for e in elements}
    if len(keys) != len(elements):
        raise ValueError(f"{data['repository']}: element keys must be unique")
    relationships = [RefRelationship(r["source"], r["target"], r["type"], r["kind"], bool(r.get("optional", False)), _levels_of(r)) for r in data.get("relationships", [])]
    chains = [Chain(c["name"], tuple((s[0], s[1], s[2], len(s) > 3 and s[3] == "reverse") for s in c["steps"])) for c in data.get("chains", [])]
    ends = {k for r in relationships for k in (r.source, r.target)} | {k for c in chains for s in c.steps for k in (s[0], s[2])}
    if unknown := ends - keys:
        raise ValueError(f"{data['repository']}: unknown element keys {sorted(unknown)}")
    tagged = any("levels" in item or "cross_level" in item for item in [*data["elements"], *data.get("relationships", [])])
    return Reference(repository=data["repository"], elements=elements, relationships=relationships, chains=chains, tagged=tagged)


LEVELS = ("enterprise", "solution")


def _levels_of(item: dict[str, Any]) -> frozenset[str]:
    """The levels a reference or model item belongs to (``levels``); without them, the enterprise level.

    A cross-level item (``cross_level``, or an explicit empty ``levels``: a roll-up between levels) belongs to no
    single level and counts in the union only.
    """
    if item.get("cross_level"):
        return frozenset()
    levels = item.get("levels")
    return frozenset(str(v) for v in levels) if isinstance(levels, list) else frozenset({"enterprise"})


def at_level(reference: Reference, model: dict[str, Any], level: str | None) -> tuple[Reference, dict[str, Any]]:
    """The reference and the model at one level (``enterprise`` or ``solution``); ``None`` or ``union``: all of both."""
    if level is None or level == "union":
        return reference, model
    if level not in LEVELS:
        raise ValueError(f"level is one of {', '.join(LEVELS)}, union or None, not {level!r}")
    keys = {e.key for e in reference.elements if level in e.levels}
    leveled = Reference(
        repository=reference.repository,
        elements=[e for e in reference.elements if e.key in keys],
        relationships=[r for r in reference.relationships if level in r.levels and r.source in keys and r.target in keys],
        chains=[c for c in reference.chains if all(a in keys and b in keys for a, _, b, _ in c.steps)],
    )
    return leveled, snapshot_at_level(model, level)


def snapshot_at_level(model: dict[str, Any], level: str | None) -> dict[str, Any]:
    """A run model at one level: its elements tagged with the level (no tag: enterprise) and the relationships on it
    between them; ``None`` or ``union``: the whole model."""
    if level is None or level == "union":
        return model
    if level not in LEVELS:
        raise ValueError(f"level is one of {', '.join(LEVELS)}, union or None, not {level!r}")
    ids = {e["identifier"] for e in model.get("elements", []) if level in _levels_of(e)}
    return {
        **model,
        "elements": [e for e in model.get("elements", []) if e["identifier"] in ids],
        "relationships": [r for r in model.get("relationships", []) if level in _levels_of(r) and r["source"] in ids and r["target"] in ids],
    }


def _type(value: str) -> str:
    return str(value).removeprefix("Model:")


_kind = match_kind


def map_elements(reference: Reference, model: dict[str, Any]) -> dict[str, str]:
    """Model element identifier -> reference element key: an exact name first, then an alias, then lineage. Types match as
    ``types_match`` says: a function covers a process of its layer."""
    names: dict[tuple[str, str], str] = {}
    aliases: dict[tuple[str, str], str] = {}
    for ref in reference.elements:
        for t in ref.types:
            names.setdefault((_kind(t), name_key(ref.name)), ref.key)
            for alias in ref.aliases:
                aliases.setdefault((_kind(t), name_key(alias)), ref.key)
    mapping: dict[str, str] = {}
    for e in model.get("elements", []):
        t, key = _type(e["type"]), name_key(str(e.get("name") or ""))
        found = names.get((_kind(t), key)) or aliases.get((_kind(t), key))
        if found is None:
            found = next((r.key for r in reference.elements if any(types_match(t, rt) for rt in r.types) and ({str(e.get("source") or ""), e["identifier"]} & r.lineage)), None)
        if found is not None:
            mapping[e["identifier"]] = found
    return mapping


# Element types whose name is a closed choice among structural candidates (what the LLM name adds)
NAMED_TYPES = ("ApplicationComponent", "ApplicationService", "DataObject", "BusinessFunction", "BusinessProcess")


def naming(reference: Reference, model: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per named type: of the elements whose lineage maps to a reference element and that carry a structure name,
    how many match its name (normalized) with the LLM-chosen name and with the structural name, and with an alias."""
    out: dict[str, dict[str, int]] = {}
    for t in NAMED_TYPES:
        counts = {"compared": 0, "chosen": 0, "chosen_alias": 0, "structural": 0, "structural_alias": 0}
        for e in model.get("elements", []):
            if _type(e["type"]) != t or not e.get("structure_name"):
                continue
            ref = next((r for r in reference.elements if t in r.types and ({str(e.get("source") or ""), e["identifier"]} & r.lineage)), None)
            if ref is None:
                continue
            exact = {name_key(ref.name)}
            alias = exact | {name_key(a) for a in ref.aliases}
            chosen, structural = name_key(str(e.get("name") or "")), name_key(str(e["structure_name"]))
            counts["compared"] += 1
            counts["chosen"] += chosen in exact
            counts["chosen_alias"] += chosen in alias
            counts["structural"] += structural in exact
            counts["structural_alias"] += structural in alias
        if counts["compared"]:
            out[t] = counts
    return out


def evaluate(reference: Reference, model: dict[str, Any], *, level: str | None = None) -> dict[str, Any]:
    """Recall and precision per element type and relationship kind, splits, chains, for one model.

    ``level`` (``enterprise``, ``solution`` or ``union``) scores one abstraction level of both; ``None`` keeps
    every element and relationship, as before levels existed.
    """
    reference, model = at_level(reference, model, level)
    mapping = map_elements(reference, model)
    by_key = {r.key: r for r in reference.elements}
    covered: dict[str, list[str]] = defaultdict(list)  # reference key -> model identifiers
    for identifier, key in mapping.items():
        covered[key].append(identifier)

    elements: dict[str, dict[str, Any]] = {}

    def slot(t: str) -> dict[str, Any]:
        return elements.setdefault(t, {"required": 0, "covered": 0, "model": 0, "mapped": 0, "missing": [], "extra": [], "splits": {}})

    for ref in reference.elements:
        if ref.optional:
            continue
        s = slot(ref.types[0])
        s["required"] += 1
        if covered.get(ref.key):
            s["covered"] += 1
            if len(covered[ref.key]) > 1:
                s["splits"][ref.name] = len(covered[ref.key])
        else:
            s["missing"].append(ref.name)
    for e in model.get("elements", []):
        s = slot(_type(e["type"]))
        s["model"] += 1
        if e["identifier"] in mapping:
            s["mapped"] += 1
        else:
            s["extra"].append(str(e.get("name") or e["identifier"]))
    for s in elements.values():
        s["recall"] = round(s["covered"] / s["required"], 3) if s["required"] else None
        s["precision"] = round(s["mapped"] / s["model"], 3) if s["model"] else None
        s["missing"].sort()
        s["extra"].sort()

    present = {(mapping.get(r["source"]), _type(r["type"]), mapping.get(r["target"])) for r in model.get("relationships", [])}
    relationships: dict[str, dict[str, Any]] = {}
    for ref in reference.relationships:
        if ref.optional or by_key[ref.source].optional or by_key[ref.target].optional:
            continue
        s = relationships.setdefault(ref.kind, {"required": 0, "matched": 0, "missing": []})
        s["required"] += 1
        if (ref.source, ref.type, ref.target) in present:
            s["matched"] += 1
        else:
            s["missing"].append(f"{by_key[ref.source].name} -{ref.type}-> {by_key[ref.target].name}")
    for s in relationships.values():
        s["recall"] = round(s["matched"] / s["required"], 3) if s["required"] else None
    wanted = {(r.source, r.type, r.target) for r in reference.relationships}
    assessable = [r for r in model.get("relationships", []) if r["source"] in mapping and r["target"] in mapping]
    correct = sum(1 for r in assessable if (mapping[r["source"]], _type(r["type"]), mapping[r["target"]]) in wanted)
    totals = {
        "model": len(model.get("relationships", [])),
        "assessable": len(assessable),
        "unassessable": len(model.get("relationships", [])) - len(assessable),
        "correct": correct,
        "precision": round(correct / len(assessable), 3) if assessable else None,
    }

    chains = []
    for chain in reference.chains:
        found = sum(1 for a, t, b, rev in chain.steps if (a, t, b) in present or (rev and (b, t, a) in present))
        chains.append({"name": chain.name, "steps": len(chain.steps), "present": found, "complete": found == len(chain.steps)})

    optional = [r for r in reference.elements if r.optional]
    required = sum(s["required"] for s in elements.values())
    return {
        "elements": elements,
        "relationships": relationships,
        "relationship_totals": totals,
        "chains": chains,
        "optional": {"total": len(optional), "covered": sum(1 for r in optional if covered.get(r.key)), "names": sorted(r.name for r in optional)},
        "element_recall": round(sum(s["covered"] for s in elements.values()) / required, 3) if required else None,
        "element_precision": round(len(mapping) / len(model.get("elements", [])), 3) if model.get("elements") else None,
        "relationship_recall": _ratio(relationships, "matched", "required"),
        "naming": naming(reference, model),
        "model_size": len(model.get("elements", [])),
        "reference_size": required,
    }


def _ratio(groups: dict[str, dict[str, Any]], part: str, whole: str) -> float | None:
    total = sum(g[whole] for g in groups.values())
    return round(sum(g[part] for g in groups.values()) / total, 3) if total else None


def load_references(folder: str | Path) -> dict[str, Reference]:
    """Every reference model in a folder, by repository name."""
    references = {}
    for path in sorted(Path(folder).glob("*.json")):
        reference = parse_reference(json.loads(path.read_text(encoding="utf-8")))
        references[reference.repository] = reference
    return references


def evaluate_session(session_dir: str | Path, references_dir: str | Path, run: int | None = None) -> dict[str, Any]:
    """Every exported run of a session whose repository has a reference model, with the mean per repository."""
    references = load_references(references_dir)
    repositories: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(session_dir, "models").glob("*_run*.json")):
        match = re.match(r"(.+)_([^_]+)_run(\d+)\.json$", path.name)
        if not match or match.group(1) not in references or (run is not None and int(match.group(3)) != run):
            continue
        repo, model_name, number = match.group(1), match.group(2), int(match.group(3))
        result = evaluate(references[repo], json.loads(path.read_text(encoding="utf-8")))
        repositories.setdefault(repo, {"runs": []})["runs"].append({"run": number, "model": model_name, **result})
    for entry in repositories.values():
        entry["runs"].sort(key=lambda r: r["run"])
        runs = entry["runs"]
        mean = lambda field: round(sum(r[field] or 0 for r in runs) / len(runs), 3)  # noqa: E731 - a one-line helper
        entry["mean"] = {f: mean(f) for f in ("element_recall", "element_precision", "relationship_recall")}
        entry["mean"]["relationship_precision"] = round(sum(r["relationship_totals"]["precision"] or 0 for r in runs) / len(runs), 3)
    return {"session": Path(session_dir).name, "repositories": repositories}


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def table_lines(payload: dict[str, Any]) -> list[str]:
    """The console table: per repository the means, then recall/precision per element type and relationship kind (run 1)."""
    lines: list[str] = []
    for repo, entry in sorted(payload["repositories"].items()):
        mean, first = entry["mean"], entry["runs"][0]
        lines.append(
            f"== {repo} ({len(entry['runs'])} runs): elements R {_pct(mean['element_recall'])} P {_pct(mean['element_precision'])}; "
            f"relationships R {_pct(mean['relationship_recall'])} P {_pct(mean['relationship_precision'])}; "
            f"size {first['model_size']} vs reference {first['reference_size']}"
        )
        for t, s in sorted(first["elements"].items()):
            splits = f", splits {sum(s['splits'].values())} into {len(s['splits'])}" if s["splits"] else ""
            lines.append(f"   {t:<22} R {s['covered']}/{s['required']} {_pct(s['recall']):>5}   P {s['mapped']}/{s['model']} {_pct(s['precision']):>5}{splits}")
        for kind, s in sorted(first["relationships"].items()):
            lines.append(f"   rel {kind:<18} R {s['matched']}/{s['required']} {_pct(s['recall']):>5}")
        totals = first["relationship_totals"]
        lines.append(f"   rel precision {totals['correct']}/{totals['assessable']} {_pct(totals['precision'])} ({totals['unassessable']} unassessable)")
        if first["chains"]:
            lines.append("   chains: " + ", ".join(f"{c['name']} {c['present']}/{c['steps']}" for c in first["chains"]))
        if first.get("naming"):
            lines.append(
                "   names LLM / structure vs reference (alias): "
                + ", ".join(f"{t} {n['chosen']}/{n['structural']} of {n['compared']} ({n['chosen_alias']}/{n['structural_alias']})" for t, n in sorted(first["naming"].items()))
            )
    return lines


def write_report(payload: dict[str, Any], out_dir: str | Path) -> dict[str, str]:
    """summary.json plus a markdown page per repository (missing, extra, split elements and missing relationships per run)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    pages = {}
    for repo, entry in sorted(payload["repositories"].items()):
        text = [f"# Reference evaluation: {repo}", "", f"Session {payload['session']}.", ""]
        for r in entry["runs"]:
            text += [f"## Run {r['run']}", "", "| Type | Recall | Precision | Missing | Extra | Splits |", "| --- | --- | --- | --- | --- | --- |"]
            for t, s in sorted(r["elements"].items()):
                splits = ", ".join(f"{n} ({k})" for n, k in sorted(s["splits"].items()))
                text.append(f"| {t} | {s['covered']}/{s['required']} | {s['mapped']}/{s['model']} | {', '.join(s['missing'])} | {', '.join(s['extra'])} | {splits} |")
            text += ["", "| Relationship kind | Recall | Missing |", "| --- | --- | --- |"]
            for kind, s in sorted(r["relationships"].items()):
                text.append(f"| {kind} | {s['matched']}/{s['required']} | {'; '.join(s['missing'])} |")
            text += ["", "| Chain | Steps present | Complete |", "| --- | --- | --- |"]
            text += [f"| {c['name']} | {c['present']}/{c['steps']} | {'yes' if c['complete'] else 'no'} |" for c in r["chains"]]
            text.append("")
        page = out / f"{repo}.md"
        page.write_text("\n".join(text), encoding="utf-8")
        pages[repo] = str(page)
    return pages
