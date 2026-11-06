"""Business actors from documentation (pure; one closed LLM multi-choice per repository).

The same pattern as the application grouping, applied to the business layer. Structure proposes: the extraction's
business concepts of kind actor, kept for an application only where one documentation section mentions both the
concept and the application (its name or its units: ``application_grouping.doc_headings``). The LLM chooses which
of them the application serves; "none" is an empty list. Structure verifies: an answer outside the listed
candidates is dropped, an unreadable answer gives no actor.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deriva.common.json_utils import extract_json_from_response
from deriva.modules.derivation.application_grouping import clean_heading, doc_headings, doc_sections, mentions_word


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


_ITEM = re.compile(r"^([-*+]|\d+[.)]|>)\s+")
_TERM = re.compile(r"^(?:\*\*|__)([^*_]+?)[.:]?(?:\*\*|__)[.:]?\s+")


def _sentences(lines: list[str]) -> list[str]:
    """The sentences of a section's prose: paragraphs and list items split at sentence ends, markup left out; a table
    row is no sentence."""
    blocks: list[list[str]] = [[]]
    for line in lines:
        text = line.strip()
        if not text or _ITEM.match(text) or text.startswith("|"):
            blocks.append([])
        if text and not text.startswith("|"):
            blocks[-1].append(_ITEM.sub("", text))
    out: list[str] = []
    for block in blocks:
        # A glossary entry's bold term ("**Shopper.** A Shopper buys") stays with its definition
        prose = clean_heading(_TERM.sub(r"\1: ", " ".join(block)))
        out += [s for s in re.split(r"(?<=[.!?])\s+(?=[\"'(A-Z0-9])", prose) if s]
    return out


def _cut(sentence: str, word: str, max_chars: int) -> str:
    """A sentence of at most ``max_chars`` characters around a word's first use; "..." marks a cut."""
    if len(sentence) <= max_chars:
        return sentence
    found = re.search(rf"(?i)(?<![\w-]){re.escape(word)}(?![\w-])", sentence)
    start = max(0, min((found.start() if found else 0) - max_chars // 2, len(sentence) - max_chars))
    end = start + max_chars
    return ("..." if start else "") + sentence[start:end].strip() + ("..." if end < len(sentence) else "")


def actor_evidence(
    documents: dict[str, str], applications: dict[str, set[str]], concepts: dict[str, str], verified: dict[str, list[str]], max_chars: int
) -> dict[str, dict[str, str]]:
    """Application key -> candidate name -> the documentation that names it with the application: of the sections
    (path order) that mention both, the first sentence that names the candidate and the application, else the first
    that names the candidate, cut to ``max_chars`` around the candidate, with the file and heading."""
    # A section counts by its prose, as its sentences do: fenced code names nothing
    sections = [(path, heading, f"{heading}\n" + "\n".join(prose), _sentences(prose)) for path, _, heading, _, prose in doc_sections(documents)]
    out: dict[str, dict[str, str]] = {}
    for app, ids in sorted(verified.items()):
        words = {w for w in applications.get(app, set()) if w}
        for name in sorted({concepts[c] for c in ids if c in concepts}):
            named = [
                (s, path, heading)
                for path, heading, haystack, sentences in sections
                if mentions_word(haystack, name) and any(mentions_word(haystack, w) for w in words)
                for s in sentences
                if mentions_word(s, name)
            ]
            if named:
                sentence, path, heading = next((n for n in named if any(mentions_word(n[0], w) for w in words)), named[0])
                out.setdefault(app, {})[name] = f'{_cut(sentence, name, max_chars)} ({path}, "{heading}")'
    return out


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


def build_actor_prompt(
    instruction: str,
    applications: list[dict[str, Any]],
    candidates: dict[str, list[str]],
    documentation: str = "",
    evidence: dict[str, dict[str, str]] | None = None,
) -> str:
    """The actor prompt; it depends only on the instruction, the repository's introduction, the applications (key,
    name, units), their candidates and, when given, the documentation sentence per candidate."""
    shown = json.dumps(applications, sort_keys=True, separators=(",", ":"))
    listed = "\n".join(f"- {key}: {json.dumps(names)}" for key, names in candidates.items())
    intro = f"\n## Repository documentation\n{documentation}\n" if documentation else ""
    found = evidence or {}
    proof = "".join(f"- {key}:\n" + "".join(f"  - {name}: {found[key][name]}\n" for name in names if name in found[key]) for key, names in candidates.items() if found.get(key))
    proof = f"\n## Evidence per candidate\n{proof}" if proof else ""
    return f"""{instruction}
{intro}
## Applications
```json
{shown}
```

## Candidate actors per application
{listed}
{proof}
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
