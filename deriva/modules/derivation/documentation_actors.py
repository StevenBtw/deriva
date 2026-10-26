"""Business actors from documentation (pure; one closed LLM multi-choice per repository).

The same pattern as the application grouping, applied to the business layer. Structure proposes: the extraction's
business concepts of kind actor, kept for an application only where one documentation section mentions both the
concept and the application (its name or its units: ``application_grouping.doc_headings``). The LLM chooses which
of them the application serves; "none" is an empty list. Structure verifies: an answer outside the listed
candidates is dropped, an unreadable answer gives no actor.
"""

from __future__ import annotations

import json
from typing import Any

from deriva.common.json_utils import extract_json_from_response
from deriva.modules.derivation.application_grouping import doc_headings


def verified_candidates(documents: dict[str, str], applications: dict[str, set[str]], concepts: dict[str, str]) -> dict[str, list[str]]:
    """Application key -> the concept ids one documentation section mentions together with the application (its
    words: name, unit folders and names); applications without such a concept are left out. Sorted."""
    terms: dict[str, set[str]] = {f"a\x00{key}": {w for w in words if w} for key, words in applications.items()}
    terms |= {f"c\x00{cid}": {name} for cid, name in concepts.items()}
    together: dict[str, set[str]] = {}
    for heading in doc_headings(documents, terms):
        apps = [m.split("\x00", 1)[1] for m in heading.mentions if m.startswith("a\x00")]
        found = [m.split("\x00", 1)[1] for m in heading.mentions if m.startswith("c\x00")]
        for app in apps:
            together.setdefault(app, set()).update(found)
    return {app: sorted(ids) for app, ids in sorted(together.items()) if ids}


def actor_schema(candidates: dict[str, list[str]]) -> dict[str, Any]:
    """The output contract: per application, a list of its candidates as written (empty for none)."""
    return {
        "name": "documentation_actors",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "actors": {
                    "type": "object",
                    "properties": {key: {"type": "array", "items": {"type": "string", "enum": list(names)}} for key, names in candidates.items()},
                    "required": list(candidates),
                    "additionalProperties": False,
                }
            },
            "required": ["actors"],
            "additionalProperties": False,
        },
    }


def build_actor_prompt(instruction: str, applications: list[dict[str, Any]], candidates: dict[str, list[str]], documentation: str = "") -> str:
    """The actor prompt; it depends only on the instruction, the repository's introduction, the applications (key,
    name, units) and their candidates."""
    shown = json.dumps(applications, sort_keys=True, separators=(",", ":"))
    listed = "\n".join(f"- {key}: {json.dumps(names)}" for key, names in candidates.items())
    intro = f"\n## Repository documentation\n{documentation}\n" if documentation else ""
    return f"""{instruction}
{intro}
## Applications
```json
{shown}
```

## Candidate actors per application
{listed}

Return {{"actors": {{"<application key>": ["<candidate>", ...], ...}}}}, each candidate exactly as written; an empty list where none fits."""


def parse_actors(content: str, candidates: dict[str, list[str]]) -> dict[str, list[str]]:
    """Application key -> the chosen actors that are among its candidates (sorted); none for an unreadable answer."""
    try:
        answer = json.loads(extract_json_from_response(content)).get("actors") or {}
    except ValueError, AttributeError:
        answer = {}
    chosen = answer if isinstance(answer, dict) else {}
    out: dict[str, list[str]] = {}
    for key, names in candidates.items():
        picked = chosen.get(key)
        out[key] = sorted({str(n) for n in picked if n in names}) if isinstance(picked, list) else []
    return out
