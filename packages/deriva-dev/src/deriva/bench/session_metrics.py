"""Session measures from a benchmark's run snapshots and call logs (read-only; one or more sessions).

- **Identities:** consistency under the source-derived id and under a common identity every system has (type +
  canonical name key), so a baseline without source ids is compared like Deriva.
- **cons and J̄:** the share of objects in every run, and the mean Jaccard over all run pairs.
- **Layers and origin:** element consistency per ArchiMate layer; LLM-dependent elements (an LLM-created source
  node, a name chosen by a call, or a type whose step classified with the LLM in that run) apart from structural ones;
  a relationship depends on the LLM when an endpoint does or an LLM derived it.
- **Two levels:** per decision type, answer stability (the same prompt answered alike in every run), decision
  stability (each item decided alike) and Krippendorff's alpha (nominal) over the items, next to model consistency.
- **Out of candidates:** per model and decision type, the calls, the typed answers that were asked again and the
  answers outside the candidates (name choices, extraction labels that matched no item).
- **Agreement across LLMs:** the same over the runs of all sessions' models together.
"""

from __future__ import annotations

import ast
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

from deriva.adapters.archimate.models import ELEMENT_TYPES, layer_of
from deriva.common.json_utils import extract_json_from_response
from deriva.common.naming import name_key
from deriva.common.ocel import hash_content
from deriva.modules.analysis import compute_answer_stability, decision_content, decision_stability
from deriva.modules.analysis.semantic_matching import match_elements

NAMING_SCHEMAS = frozenset({"element_name_choice", "element_naming"})
EXTRACTION_LLM_STEPS = frozenset({"DirectoryClassification", "BusinessConcept", "Technology"})
ALL_MODELS = "all LLMs"


def _metadata(session: Path) -> dict[str, Any]:
    return json.loads((Path(session) / "session_metadata.json").read_text(encoding="utf-8")).get("config", {})


def _runs(session: Path) -> list[tuple[str, str, int, dict[str, Any]]]:
    """(repository, model, run number, snapshot) of every exported run of a session."""
    config = _metadata(session)
    found = []
    for repo in config.get("repositories", []):
        for model in config.get("models", []):
            prefix = f"{repo.replace('/', '_')}_{model.replace('/', '_')}_run"
            for path in sorted(Path(session, "models").glob(f"{prefix}*.json")):
                number = path.stem[len(prefix) :]
                if number.isdigit():
                    try:
                        found.append((repo, model, int(number), json.loads(path.read_text(encoding="utf-8"))))
                    except OSError, ValueError:
                        continue
    return sorted(found, key=lambda r: (r[0], r[1], r[2]))


def _calls(session: Path) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    """The LLM calls of each run, by (repository, model config, run number) from their run id."""
    by_run: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for path in sorted(Path(session, "llm").glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            try:
                call = json.loads(line)
            except ValueError:
                continue
            parts = str(call.get("run_id") or "").split(":")
            if len(parts) >= 4 and parts[-1].isdigit():
                by_run.setdefault((parts[1], parts[2], int(parts[-1])), []).append(call)
    return by_run


def _decision_type(call: dict[str, Any]) -> str:
    step = str(call.get("step") or "?")
    if call.get("schema") in NAMING_SCHEMAS:
        return f"{step} name choice"
    return step if step in EXTRACTION_LLM_STEPS else f"{step} classification"


def _share(sets: list[set[Any]]) -> float | None:
    union = set().union(*sets) if sets else set()
    return round(len(set.intersection(*sets)) / len(union), 3) if union else None


def _jbar(sets: list[set[Any]]) -> float | None:
    pairs = list(itertools.combinations(sets, 2))
    if not pairs:
        return None
    return round(sum((len(a & b) / len(a | b)) if (a | b) else 1.0 for a, b in pairs) / len(pairs), 3)


def _run_view(snapshot: dict[str, Any], classified: set[str]) -> dict[str, Any]:
    """One run's objects under both identities, with each element's layer and origin."""
    llm_nodes = {c[0] if isinstance(c, list) else c for c in (snapshot.get("graph") or {}).get("concepts", [])}
    llm_nodes |= set((snapshot.get("graph") or {}).get("technologies", []))
    keys, origin, layers = {}, {}, {}
    for e in snapshot.get("elements", []):
        name_id = (e["type"], name_key(str(e.get("name") or "")))
        keys[e["identifier"]] = name_id
        # No structural source (a baseline's free generation), an LLM-created source, a chosen name or an LLM-classified type
        llm = not e.get("source") or bool(e.get("name_choice")) or e.get("source") in llm_nodes or e["type"] in classified
        for identity in (e["identifier"], name_id):
            origin[identity] = llm
            layers[identity] = layer_of(e["type"])
    elements = {"id": set(keys), "name": set(keys.values())}
    rels: dict[str, set[Any]] = {"id": set(), "name": set()}
    for r in snapshot.get("relationships", []):
        rid = (r["source"], r["type"], r["target"])
        rname = (keys.get(r["source"]), r["type"], keys.get(r["target"]))
        llm = "llm" in str(r.get("derived_from") or "") or origin.get(r["source"], False) or origin.get(r["target"], False)
        rels["id"].add(rid)
        rels["name"].add(rname)
        origin[rid] = origin[rname] = llm
    return {"elements": elements, "relationships": rels, "origin": origin, "layers": layers}


def _identity_report(views: list[dict[str, Any]], identity: str) -> dict[str, Any]:
    elements = [v["elements"][identity] for v in views]
    rels = [v["relationships"][identity] for v in views]
    origin: dict[Any, bool] = {}
    layers: dict[Any, str] = {}
    for v in views:
        for item, llm in v["origin"].items():
            origin[item] = origin.get(item, False) or llm
        layers.update(v["layers"])

    def part(sets: list[set[Any]], keep) -> list[set[Any]]:
        return [{x for x in s if keep(x)} for s in sets]

    all_elements = set().union(*elements) if elements else set()
    report = {
        "elements": {"cons": _share(elements), "jbar": _jbar(elements), "count": len(all_elements)},
        "relationships": {"cons": _share(rels), "jbar": _jbar(rels), "count": len(set().union(*rels)) if rels else 0},
        "layers": {layer: _share(part(elements, lambda x, layer=layer: layers.get(x) == layer)) for layer in sorted({layers.get(x) for x in all_elements} - {None})},
        "origin": {},
    }
    for name, wanted in (("llm", True), ("structural", False)):
        e = part(elements, lambda x, wanted=wanted: origin.get(x, False) == wanted)
        r = part(rels, lambda x, wanted=wanted: origin.get(x, False) == wanted)
        report["origin"][name] = {"elements": _share(e), "relationships": _share(r), "count": len(set().union(*e)) if e else 0}
    return report


def consistency_rows(sessions: list[Path]) -> list[dict[str, Any]]:
    """Per repository and model (and over all models when the sessions hold several), both identities."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for session in sessions:
        calls = _calls(session)
        for repo, model, number, snapshot in _runs(session):
            classified = {str(c.get("step")) for c in calls.get((repo, model, number), []) if _decision_type(c).endswith(" classification")}
            grouped.setdefault((repo, model), []).append(_run_view(snapshot, classified))
    rows = []
    for repo in sorted({r for r, _ in grouped}):
        models = sorted(m for r, m in grouped if r == repo)
        groups = [(m, grouped[(repo, m)]) for m in models]
        if len(models) > 1:
            groups.append((ALL_MODELS, [v for m in models for v in grouped[(repo, m)]]))
        for model, views in groups:
            if len(views) >= 2:
                rows.append({"repository": repo, "model": model, "runs": len(views), "identities": {i: _identity_report(views, i) for i in ("id", "name")}})
    return rows


def krippendorff_alpha(runs: list[dict[str, Any]]) -> float | None:
    """Nominal Krippendorff's alpha with the runs as coders and the items as units (None when undefined)."""
    values: dict[str, list[str]] = {}
    for run in runs:
        for item, value in run.items():
            values.setdefault(item, []).append(repr(value))
    coincidence: Counter = Counter()
    for found in values.values():
        if len(found) < 2:
            continue
        for a, b in itertools.permutations(range(len(found)), 2):
            coincidence[(found[a], found[b])] += 1 / (len(found) - 1)
    totals: Counter = Counter()
    for (a, _), n in coincidence.items():
        totals[a] += n
    n = sum(totals.values())
    expected = n * n - sum(v * v for v in totals.values())
    if n <= 1 or expected <= 0:
        return None
    observed = sum(v for (a, b), v in coincidence.items() if a != b)
    return round(1 - (n - 1) * observed / expected, 3)


def two_level_rows(sessions: list[Path]) -> list[dict[str, Any]]:
    """Per repository, model and decision type: answer stability, decision stability and alpha over the runs."""
    rows = []
    for session in sessions:
        calls = _calls(session)
        runs: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
        for repo, model, number, snapshot in _runs(session):
            runs.setdefault((repo, model), []).append((number, snapshot))
        for (repo, model), numbered in sorted(runs.items()):
            if len(numbered) < 2:
                continue
            answers: dict[str, dict[tuple[str, str], list[str | None]]] = {}
            for number, _ in numbered:
                for c in calls.get((repo, model, number), []):
                    content = c.get("response")
                    answer = hash_content(decision_content(content)) if content and not c.get("error") else None
                    answers.setdefault(str(number), {}).setdefault((_decision_type(c), str(c.get("cache_key"))), []).append(answer)
            for number, _ in numbered:
                answers.setdefault(str(number), {})
            answered = {a.step: a for a in compute_answer_stability(answers)}
            decided: dict[str, list[dict[str, Any]]] = {}
            for _, snapshot in numbered:
                per_type: dict[str, dict[str, Any]] = {}
                for step, items in (snapshot.get("extraction_decisions") or {}).items():
                    per_type[step] = dict(items or {})
                for e in snapshot.get("elements", []):
                    if e.get("name_choice"):
                        per_type.setdefault(f"{e['type']} name choice", {})[str(e.get("source") or e["identifier"])] = e.get("name")
                for c in snapshot.get("candidates", []):
                    if c.get("stage") in ("created", "llm_rejected"):
                        per_type.setdefault(f"{c['type']} classification", {})[str(c.get("source"))] = c["stage"]
                for kind, items in per_type.items():
                    decided.setdefault(kind, []).append(items)
            kinds = sorted(set(answered) | {k for k in decided if not k.endswith(" classification") or k in answered})
            for kind in kinds:
                per_run = decided.get(kind, [])
                complete = per_run if len(per_run) == len(numbered) else per_run + [{}] * (len(numbered) - len(per_run))
                stable = decision_stability(complete) if per_run else None
                a = answered.get(kind)
                rows.append(
                    {
                        "repository": repo,
                        "model": model,
                        "decision": kind,
                        "answers": {"identical": a.identical if a else 0, "prompts": a.prompts if a else 0},
                        "decisions": {"stable": stable.stable, "items": stable.items} if stable else {"stable": 0, "items": 0},
                        "alpha": krippendorff_alpha(complete) if per_run else None,
                    }
                )
    return rows


def _candidates_of(prompt: str) -> set[str]:
    listed = prompt.split("## Candidates", 1)[-1].split("\n\nReturn", 1)[0]
    found = set()
    for line in listed.splitlines():
        if line.startswith("- "):
            try:
                found.add(json.loads(line[2:]))
            except ValueError:
                continue
    return found


def out_of_candidate_rows(sessions: list[Path]) -> list[dict[str, Any]]:
    """Per model and decision type: calls, typed answers asked again (more than one request) and answers outside the
    candidates (a name choice naming none; extraction labels for no item, twice, or missing)."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}

    def row(model: str, kind: str) -> dict[str, Any]:
        return rows.setdefault((model, kind), {"model": model, "decision": kind, "calls": 0, "re_asked": 0, "outside": 0})

    for session in sessions:
        models = _metadata(session).get("models", [])
        model = models[0] if len(models) == 1 else ", ".join(models)
        for calls in _calls(session).values():
            for c in calls:
                if c.get("schema") != "element_name_choice" or c.get("error"):
                    continue
                r = row(model, _decision_type(c))
                r["calls"] += 1
                try:
                    answer = json.loads(extract_json_from_response(str(c.get("response") or ""))).get("name")
                except ValueError, AttributeError:
                    answer = None
                r["outside"] += answer not in _candidates_of(str(c.get("prompt") or ""))
        events = Path(session, "ocel", "benchmark_events.jsonl")
        for line in events.open(encoding="utf-8") if events.is_file() else []:
            event = json.loads(line)
            attrs = event.get("attributes") or {}
            step = str(attrs.get("config_id") or "")
            if step not in EXTRACTION_LLM_STEPS:
                continue
            if event.get("activity") == "LLMQuery":
                r = row(model, step)
                r["calls"] += 1
                r["re_asked"] += str(attrs.get("requests")) not in ("1", "None", "", "0")
            elif event.get("activity") == "ExtractConfig":
                raw = attrs.get("stats")
                try:
                    stats = raw if isinstance(raw, dict) else ast.literal_eval(raw) if raw else {}
                except ValueError, SyntaxError:
                    stats = {}
                issues = stats.get("issues") if isinstance(stats, dict) else None
                if isinstance(issues, dict):
                    row(model, step)["outside"] += sum(v for v in issues.values() if isinstance(v, int))
    return [rows[k] for k in sorted(rows)]


# A match on the name (exact or fuzzy) with the same type counts; each reference element at most once
NAME_MATCHES = frozenset({"exact", "fuzzy_name"})
DERIVED_TYPES = frozenset(ELEMENT_TYPES) - {"Artifact"}  # Artifact belongs to the export's detail level


def golden_comparison(
    derived: list[dict[str, Any]],
    reference: list[Any],
    aliases: dict[str, list[str]] | None = None,
    derivable: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recall and precision of derived elements against a hand-made reference model, overall and per layer.

    A reference element is found by a derived element of its type with the same or a similar name, or with a name the
    user accepted for it by hand (``aliases``: reference id -> names). ``derivable`` (reference id -> {derivable,
    reason}, the user's classification) gives the recall on the derivable subset; the derivable types are the 13
    derived types. Precision counts each found reference element once, as the model-quality report does.
    """
    aliases, derivable = aliases or {}, derivable or {}
    found = {m.reference_id for m in match_elements(derived, reference) if m.match_type in NAME_MATCHES and m.derived_type == m.reference_type}
    by_type: dict[str, set[str]] = {}
    for d in derived:
        by_type.setdefault(str(d.get("type")), set()).add(name_key(str(d.get("name") or "")))
    manual = {r.identifier for r in reference if r.identifier not in found and any(name_key(a) in by_type.get(r.element_type, set()) for a in aliases.get(r.identifier, []))}
    found |= manual

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    layers = {}
    for layer in sorted({r.layer for r in reference if r.layer}):
        in_layer = [r for r in reference if r.layer == layer]
        derived_in_layer = [d for d in derived if layer_of(str(d.get("type"))) == layer]
        hits = sum(1 for r in in_layer if r.identifier in found)
        layers[layer] = {"recall": share(hits, len(in_layer)) or 0.0, "precision": share(hits, len(derived_in_layer)), "reference": len(in_layer)}
    typed = [r for r in reference if r.element_type in DERIVED_TYPES]
    labelled = [r for r in reference if r.identifier in derivable]
    can = [r for r in labelled if derivable[r.identifier].get("derivable")]
    return {
        "precision": share(len(found), len(derived)) or 0.0,
        "recall": share(len(found), len(reference)) or 0.0,
        "reference_elements": len(reference),
        "layers": layers,
        "derivable_types_recall": share(sum(1 for r in typed if r.identifier in found), len(typed)),
        "derivable_recall": share(sum(1 for r in can if r.identifier in found), len(can)),
        "derivable_labelled": len(labelled),
        "manual_matches": len(manual),
    }


def manual_inputs(reference_path: str | Path) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """The user's files next to a reference model: ``<repo>.matches.json`` (aliases) and ``<repo>.derivable.json``."""
    base = Path(reference_path)
    loaded = []
    for suffix in (".matches.json", ".derivable.json"):
        path = base.with_suffix(suffix)
        try:
            loaded.append(json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {})
        except OSError, ValueError:
            loaded.append({})
    return loaded[0], loaded[1]


def session_report(sessions: list[Path]) -> dict[str, Any]:
    """Everything above for one or more sessions (several: agreement across their LLMs as well)."""
    sessions = [Path(s) for s in sessions if Path(s, "session_metadata.json").is_file()]
    if not sessions:
        return {}
    return {"consistency": consistency_rows(sessions), "two_level": two_level_rows(sessions), "out_of_candidates": out_of_candidate_rows(sessions)}
