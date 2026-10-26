"""Application grouping from documentation (pure; one closed LLM choice per repository).

Structure proposes, the LLM chooses, structure verifies. The candidates are closed and come from structure: the
title of the repository's root README, split at its dash ("Shop System - Online Store Application"), and each
top-level component's own name without its kind words (the choice to stay its own application). The LLM assigns
every component one candidate; an answer outside the set, or none, keeps the component's own name. A candidate
that two or more components choose is an application that groups them.

The headings extractor (``doc_headings``) is shared with the steps that take their candidates from documentation:
each heading with the units and domains its section mentions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from deriva.common.json_utils import extract_json_from_response
from deriva.common.naming import name_key

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_DASH = re.compile(r"\s+[-–—]\s+")


@dataclass(frozen=True)
class Heading:
    """One documentation heading: its file, level, text without markup, and the keys its section mentions."""

    path: str
    level: int
    text: str
    mentions: frozenset[str] = field(default_factory=frozenset)


def clean_heading(text: str) -> str:
    """A heading without images, link targets, emphasis or code marks."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    return " ".join(text.split())


def doc_headings(documents: dict[str, str], terms: dict[str, set[str]], max_level: int = 3) -> list[Heading]:
    """Every heading up to ``max_level`` of the documentation files (path order, fenced code skipped), with the keys of
    ``terms`` (key -> its words, as written in folder or element names) whose word appears in the heading or the text
    under it, up to the next heading."""
    out: list[Heading] = []
    for path in sorted(documents):
        sections: list[tuple[int, str, list[str]]] = []
        fenced = False
        for line in documents[path].splitlines():
            if line.strip().startswith("```"):
                fenced = not fenced
                continue
            match = None if fenced else _HEADING.match(line)
            if match:
                sections.append((len(match.group(1)), clean_heading(match.group(2)), []))
            elif sections:
                sections[-1][2].append(line)
        for level, text, body in sections:
            if level > max_level or not text:
                continue
            haystack = f"{text}\n" + "\n".join(body)
            mentions = frozenset(key for key, words in terms.items() if any(re.search(rf"(?i)(?<![\w-]){re.escape(w)}(?![\w-])", haystack) for w in words if w))
            out.append(Heading(path=path, level=level, text=text, mentions=mentions))
    return out


def _readme(documents: dict[str, str], folder: str) -> str | None:
    """The README directly in a folder, if any."""
    return next((p for p in sorted(documents) if p.rsplit("/", 1)[0] == folder and p.rsplit("/", 1)[-1].lower().startswith("readme")), None)


def introduction(documents: dict[str, str], repo: str, max_chars: int) -> str:
    """The root README's introduction: its text under the title up to the next heading (fenced code, images and link
    targets left out, emphasis removed), as one line, capped at ``max_chars``."""
    readme = _readme(documents, repo)
    if readme is None:
        return ""
    lines: list[str] = []
    started = fenced = False
    for line in documents[readme].splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _HEADING.match(line):
            if started:
                break
            started = True
            continue
        if started:
            lines.append(line.lstrip("> "))
    return clean_heading(" ".join(lines))[:max_chars]


def title_parts(documents: dict[str, str], repo: str) -> list[str]:
    """The root README's title (its first level-1 heading), split at its dash into parts."""
    readme = _readme(documents, repo)
    if readme is None:
        return []
    title = next((h.text for h in doc_headings({readme: documents[readme]}, {}, max_level=1)), "")
    return [part.strip() for part in _DASH.split(title) if part.strip()]


def own_name(name: str, kind_words: tuple[str, ...]) -> str:
    """A component's own application name: its name without leading or trailing kind words, written as it is
    (punctuation kept); the whole name when nothing else is left."""
    kinds = {k.casefold() for k in kind_words}
    words = name.split()
    while len(words) > 1 and words[-1].casefold() in kinds:
        words = words[:-1]
    while len(words) > 1 and words[0].casefold() in kinds:
        words = words[1:]
    return " ".join(words)


def grouping_candidates(titles: list[str], component_names: list[str]) -> list[str]:
    """The closed candidate set: the title's parts, then each component's own name; one per name key, as written first."""
    seen: set[str] = set()
    out: list[str] = []
    for candidate in [*titles, *component_names]:
        key = name_key(candidate)
        if key and key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def grouping_schema(keys: list[str], candidates: list[str]) -> dict[str, Any]:
    """The output contract: per component key, one of the candidates as written."""
    return {
        "name": "application_grouping",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "object",
                    "properties": {key: {"type": "string", "enum": list(candidates)} for key in keys},
                    "required": list(keys),
                    "additionalProperties": False,
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        },
    }


def build_grouping_prompt(instruction: str, components: list[dict[str, str]], candidates: list[str], documentation: str = "", whole: int = 0, mark_name: bool = False) -> str:
    """The grouping prompt; it depends only on the instruction, the repository's introduction, the components (key,
    name, folder, own README title) and the candidates, the first ``whole`` of which name the whole repository (with
    ``mark_name`` and more than one, the first is marked as the name in the title)."""
    listed = "\n".join(f"- {json.dumps(c)}" for c in candidates[whole:])
    mark = mark_name and whole > 1
    titled = "\n".join(f"- {json.dumps(c)}{' (the name in the title)' if mark and i == 0 else ''}" for i, c in enumerate(candidates[:whole]))
    shown = json.dumps(components, sort_keys=True, separators=(",", ":"))
    intro = f"\n## Repository documentation\n{documentation}\n" if documentation else ""
    repository = f"\n## Candidates naming the whole repository (its title)\n{titled}\n" if titled else ""
    return f"""{instruction}
{intro}
## Components
```json
{shown}
```
{repository}
## Candidates naming one component (its own application)
{listed}

Return {{"assignments": {{"<component key>": "<candidate>", ...}}}} with one candidate exactly as written for every component."""


def parse_grouping(content: str, fallback: dict[str, str], candidates: list[str]) -> dict[str, str]:
    """Component key -> its application candidate: the answer where it is one of the candidates, else the component's
    own name (``fallback``); an unreadable answer keeps every component's own name."""
    try:
        answer = json.loads(extract_json_from_response(content)).get("assignments") or {}
    except ValueError, AttributeError:
        answer = {}
    allowed = set(candidates)
    chosen = answer if isinstance(answer, dict) else {}
    return {key: str(chosen[key]) if chosen.get(key) in allowed else own for key, own in fallback.items()}


def applications(assignment: dict[str, str]) -> list[tuple[str, list[str]]]:
    """(application name, its component keys) per candidate two or more components chose, sorted."""
    groups: dict[str, list[str]] = {}
    for key, candidate in assignment.items():
        groups.setdefault(candidate, []).append(key)
    return sorted((name, sorted(keys)) for name, keys in groups.items() if len(keys) >= 2)
