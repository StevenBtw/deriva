"""Business concepts from candidate terms (BusinessConcept v2): structure decides the candidates, the LLM classifies.

The NLP adapter (adapters/nlp) gives candidate terms in their source language, each with an English form and
its occurrences. This module merges them into one candidate per English identity (the canonical name
key), marks structural support (type definition and directory names), keeps the candidates with evidence, sizes
the list by the share of evidence it holds (with a budget cap), batches it by a stable hash, builds the
closed classification prompt, parses the labels and turns the accepted candidates into concept nodes.
Names and document references never come from the LLM.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from deriva.common.naming import _words, name_key, singularize

from .base import current_timestamp, generate_file_node_id

# Business labels and the concept type the derivation steps read
LABEL_TYPES = {
    "business_object": "entity",
    "business_process": "process",
    "business_function": "capability",
    "business_actor": "actor",
    "business_role": "actor",
    "business_event": "event",
    "business_service": "service",
}
REJECT_LABELS = ("technical", "attribute", "quality", "generic", "documentation")
LABELS = (*LABEL_TYPES, *REJECT_LABELS)


def outcome(label: str | None) -> str | None:
    """What a label does to the graph: the concept type it creates, or "rejected" for every reject label (None: no decision)."""
    return None if label is None else LABEL_TYPES.get(label, "rejected")


LANGUAGE_NAMES = {"en": "English", "de": "German", "fr": "French"}

CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "name": "business_concept_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "description": "The term, copied exactly"},
                        "label": {"type": "string", "enum": list(LABELS), "description": "One business label or one reject label"},
                    },
                    "required": ["term", "label"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ConceptCandidate:
    """All source terms with one English identity, with their evidence."""

    key: str
    name: str
    kind: str  # "noun" or "verb"
    count: int
    documents: dict[str, int]  # document path -> occurrences
    originals: list[dict[str, Any]]  # {"term", "language", "count"}, most frequent first
    snippets: list[str]
    code_support: bool = False
    snippet_paths: list[str] = field(default_factory=list)  # the document of each snippet
    score: float = field(default=0.0, compare=False)


def _title(words: list[str], singular_head: bool) -> str:
    words = list(words)
    if singular_head and words:
        words[-1] = singularize(words[-1])
    return " ".join(w[:1].upper() + w[1:] for w in words)


def _snippets(occurrences: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(snippet, document path): the first occurrence in the document that mentions the candidate most (ties
    by path), then the first occurrence in the next such document; with one document, its next occurrence
    with other context."""
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in occurrences:
        by_path[o["path"]].append(o)
    order = sorted(by_path, key=lambda p: (-len(by_path[p]), p))
    for path in order:
        by_path[path].sort(key=lambda o: (o["segment"], o["start"]))
    first = by_path[order[0]][0]["snippet"]
    if len(order) > 1:
        return [(first, order[0]), (by_path[order[1]][0]["snippet"], order[1])]
    other = next((o["snippet"] for o in by_path[order[0]][1:] if o["snippet"] != first), None)
    return [(first, order[0])] if other is None else [(first, order[0]), (other, order[0])]


_MARKUP_LINE = re.compile(r"^\s*(#|\[!\[|!\[|<|```|~~~)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def system_description(text: str, max_chars: int) -> str:
    """The prose of a README's opening: headings, images, badges, HTML, tables and code blocks left out, links
    reduced to their text, emphasis and code marks removed, cut to `max_chars` at a word boundary (0: no description)."""
    if max_chars <= 0:
        return ""
    prose, in_code = [], False
    for line in text.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or not line.strip() or _MARKUP_LINE.match(line) or "|" in line:
            continue
        prose.append(_LINK.sub(r"\1", _IMAGE.sub("", line)).replace("**", "").replace("__", "").replace("`", "").strip())
    joined = " ".join(" ".join(prose).split())
    if len(joined) <= max_chars:
        return joined
    return joined[:max_chars].rsplit(" ", 1)[0]


def merge_candidates(tool_candidates: list[dict[str, Any]], repo_name: str) -> list[ConceptCandidate]:
    """One candidate per English identity; the repository's own name is not a candidate.

    The display name is the most frequent English spelling when the term occurs in English,
    otherwise the most frequent translation (title case, singular head).
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repo_key = name_key(repo_name)
    for c in tool_candidates:
        key = name_key(c["english"])
        if key and key != repo_key:
            groups[key].append(c)
    merged = []
    for key in sorted(groups):
        members = groups[key]
        english: Counter[str] = Counter()
        translated: Counter[str] = Counter()
        originals: Counter[tuple[str, str]] = Counter()
        kinds: Counter[str] = Counter()
        documents: Counter[str] = Counter()
        occurrences: list[dict[str, Any]] = []
        for m in members:
            if m["language"] == "en":
                english[_title(m["english"].split(), singular_head=False)] += m["count"]
            else:
                translated[_title(m["english"].split(), singular_head=True)] += m["count"]
            originals[(m["term"], m["language"])] += m["count"]
            kinds[m["kind"]] += m["count"]
            documents.update(o["path"] for o in m["occurrences"])
            occurrences.extend(m["occurrences"])
        pool = english or translated
        snippets = _snippets(occurrences)
        merged.append(
            ConceptCandidate(
                key=key,
                name=sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))[0][0],
                kind="noun" if kinds["noun"] >= kinds["verb"] else "verb",
                count=sum(m["count"] for m in members),
                documents=dict(sorted(documents.items())),
                originals=[{"term": t, "language": lang, "count": n} for (t, lang), n in sorted(originals.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][0]))],
                snippets=[s for s, _ in snippets],
                snippet_paths=[path for _, path in snippets],
            )
        )
    return merged


def _word_key(name: str) -> tuple[str, ...]:
    return tuple(singularize(w).casefold() for w in _words(name) if w.isalpha())


def _ngrams(names: list[str], longest: int = 4) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for name in names:
        words = _word_key(name)
        for n in range(1, longest + 1):
            out.update(words[i : i + n] for i in range(len(words) - n + 1))
    return out


def add_support(candidates: list[ConceptCandidate], code_names: list[str]) -> list[ConceptCandidate]:
    """Mark candidates whose words are a contiguous part of a code name (type definition or directory).

    Structure only: nothing an LLM decided upstream (such as the concepts DirectoryClassification made)
    changes which candidates the classifier sees.
    """
    code = _ngrams(code_names)
    out = []
    for c in candidates:
        words = _word_key(c.name)
        out.append(replace(c, code_support=bool(words) and words in code))
    return out


def _score(c: ConceptCandidate, support_factor: float) -> float:
    score = math.log(1 + len(c.documents)) * math.log(1 + c.count)
    score *= support_factor if c.code_support else 1.0
    return round(score, 12)


def select_candidates(
    candidates: list[ConceptCandidate],
    evidence_min_count: int,
    evidence_share: float,
    max_candidates: int,
    support_factor: float,
    keep_ties: bool = False,
) -> tuple[list[ConceptCandidate], dict[str, Any]]:
    """The candidates the classifier sees.

    A candidate qualifies with at least `evidence_min_count` occurrences or with code support;
    code support multiplies its evidence score by `support_factor`.
    Ranked by evidence score, the list is the smallest prefix holding `evidence_share` of the
    total score, so it follows both the size of the documentation and how spread its vocabulary is.
    With `keep_ties` the prefix runs to the end of the tie group at the cut (equal evidence, same
    decision); without it the key order decides inside that group (config versions before the switch).
    `max_candidates` is a budget guard; the stats say when it binds.
    """
    qualified = [replace(c, score=_score(c, support_factor)) for c in candidates if c.count >= evidence_min_count or c.code_support]
    ranked = sorted(qualified, key=lambda c: (-c.score, c.key))
    total, running, share_size = sum(c.score for c in ranked), 0.0, len(ranked)
    for i, c in enumerate(ranked, 1):
        running += c.score
        if running >= evidence_share * total - 1e-9:
            share_size = i
            break
    size = share_size
    if keep_ties:
        while 0 < size < len(ranked) and ranked[size].score == ranked[size - 1].score:
            size += 1
    selected = ranked[: min(size, max_candidates)]
    stats = {
        "candidates": len(candidates),
        "qualified": len(ranked),
        "share_size": share_size,
        "ties_added": size - share_size,
        "selected": len(selected),
        "capped": size > max_candidates,
    }
    return selected, stats


def without_phrases(candidates: list[ConceptCandidate], stop_words: frozenset[str]) -> tuple[list[ConceptCandidate], int]:
    """The candidates whose English name holds none of ``stop_words``, and how many were left out.

    A term is a noun compound or a verb with its object; an English name with a determiner or an
    auxiliary is a translated clause or phrase, not a term. Applied to the selected list: a phrase
    is a real source term with a bad English form, so its evidence still counts and the selection
    keeps its cut.
    """
    kept = [c for c in candidates if not stop_words.intersection(c.name.lower().split())]
    return kept, len(candidates) - len(kept)


class Keyed(Protocol):
    """Anything classified in batches: a candidate term, a technology item."""

    @property
    def key(self) -> str: ...


def classification_batches[K: Keyed](candidates: list[K], batch_size: int) -> list[list[K]]:
    """Batches by a stable hash of the name key.

    The number of buckets is the smallest power of two that keeps the average bucket at or below
    `batch_size`, so a candidate's bucket only changes when the list crosses a power of two (then
    each bucket splits in two). Batch sizes vary around the average.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, got {batch_size}")
    if not candidates:
        return []
    buckets = 1
    while len(candidates) / buckets > batch_size:
        buckets *= 2
    grouped: dict[int, list[K]] = defaultdict(list)
    for c in candidates:
        grouped[int(hashlib.sha256(c.key.encode("utf-8")).hexdigest(), 16) % buckets].append(c)
    return [sorted(grouped[b], key=lambda c: c.key) for b in sorted(grouped)]


def build_classification_prompt(instruction: str, batch: list[ConceptCandidate], system_description: str = "", show_sources: bool = False) -> str:
    """The configured instruction, the system's own description when given, then every term with its original
    wording (when translated) and context, each context line with its document when `show_sources`."""
    lines = [instruction.strip(), ""]
    if system_description:
        lines += ["System description:", system_description, ""]
    lines.append("Terms:")
    for i, c in enumerate(batch, 1):
        shown = [o for o in c.originals if o["language"] != "en" and o["term"].casefold() != c.name.casefold()][:2]
        suffix = " (original: " + "; ".join(f'"{o["term"]}", {LANGUAGE_NAMES.get(o["language"], o["language"])}' for o in shown) + ")" if shown else ""
        lines.append(f'{i}. "{c.name}"{suffix}')
        if show_sources:
            lines.extend(f'   context ({path}): "{s}"' for s, path in zip(c.snippets, c.snippet_paths, strict=True))
        else:
            lines.extend(f'   context: "{s}"' for s in c.snippets)
    return "\n".join(lines) + "\n"


def parse_labels(content: str, batch: list[ConceptCandidate]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Labels by candidate key; answers match terms by exact text, then case-insensitively."""
    by_name = {c.name: c.key for c in batch}
    by_fold = {c.name.casefold(): c.key for c in batch}
    labels: dict[str, str] = {}
    issues: dict[str, list[str]] = {"unmatched": [], "duplicates": [], "missing": []}
    for item in json.loads(content).get("classifications", []):
        term, label = str(item.get("term", "")), item.get("label")
        if label not in LABELS:
            raise ValueError(f"Unknown label {label!r} for term {term!r}")
        key = by_name.get(term) or by_fold.get(term.casefold())
        if key is None:
            issues["unmatched"].append(term)
        elif key in labels:
            issues["duplicates"].append(term)
        else:
            labels[key] = label
    issues["missing"] = [c.name for c in batch if c.key not in labels]
    return labels, issues


def concept_nodes_and_edges(labelled: list[tuple[ConceptCandidate, str]], repo_name: str, confidence: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A BusinessConcept node for every business label, with a REFERENCES edge from each document that mentions it."""
    nodes, edges = [], []
    for candidate, label in labelled:
        if label not in LABEL_TYPES:
            continue
        concept_type = LABEL_TYPES[label]
        node_id = f"concept::{repo_name}::{candidate.key}"
        now = current_timestamp()
        nodes.append(
            {
                "node_id": node_id,
                "label": "BusinessConcept",
                "properties": {
                    "conceptName": candidate.name,
                    "conceptType": concept_type,
                    "conceptTypes": [concept_type],
                    "description": "",
                    "originSource": sorted(candidate.documents.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if candidate.documents else "",
                    "confidence": confidence,
                    "sourceTerms": [f"{o['term']} ({o['language']})" for o in candidate.originals],
                    "extracted_at": now,
                },
            }
        )
        for path in sorted(candidate.documents):
            file_node_id = generate_file_node_id(repo_name, path)
            edges.append(
                {
                    "edge_id": f"references_{file_node_id}_to_{node_id}",
                    "from_node_id": file_node_id,
                    "to_node_id": node_id,
                    "relationship_type": "REFERENCES",
                    "properties": {"confidence": confidence, "created_at": now},
                }
            )
    return nodes, edges
