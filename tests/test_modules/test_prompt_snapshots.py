"""Exact prompt strings, pinned while prompt text moves from code into versioned config.

Moving text must not change what the LLM receives (same prompt, same cache key,
same model). Each snapshot was captured from the prompt builder before the move.
"""

from __future__ import annotations

from pathlib import Path

from deriva.modules.derivation.base import (
    Candidate,
    RelationshipRule,
    build_single_candidate_prompt,
    build_unified_relationship_prompt,
)

SNAPSHOTS = Path(__file__).parent / "prompt_snapshots"


def _snapshot(name: str) -> str:
    # git may check text files out with CRLF on Windows; prompts use LF
    return (SNAPSHOTS / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_unified_relationship_prompt_is_unchanged():
    new = [{"identifier": "as_a", "name": "A", "element_type": "ApplicationService", "properties": {"source": "n1"}}]
    existing = [
        {"identifier": "ac_b", "name": "B", "element_type": "ApplicationComponent", "properties": {"source": "n2"}},
        {"identifier": "bp_c", "name": "C", "element_type": "BusinessProcess", "properties": {"source": "n3"}},
    ]

    prompt = build_unified_relationship_prompt(
        new,
        existing,
        "ApplicationService",
        [RelationshipRule("BusinessProcess", "Serving", "service serves process")],
        [RelationshipRule("ApplicationComponent", "Realization", "component realizes service")],
        instruction=_snapshot("relationship_instruction.txt"),
    )

    assert prompt == _snapshot("unified_relationship.txt")


def test_single_candidate_prompt_is_unchanged():
    cand = Candidate(node_id="n9", name="Cand", labels=["Graph", "Method"], properties={"x": 1})

    prompt = build_single_candidate_prompt(
        cand,
        "INSTRUCTION TEXT",
        "BusinessProcess",
        {"BusinessProcess": ["Alpha", "Beta"]},
        rules=_snapshot("per_candidate_rules_BusinessProcess.txt"),
    )

    assert prompt == _snapshot("single_candidate.txt")


def test_technology_prompt_is_unchanged():
    import json

    from deriva.modules.extraction.technology import build_extraction_prompt

    texts = json.loads(_snapshot("technology_params.json"))["prompt"]

    with_context = build_extraction_prompt(
        "content here",
        "setup.py",
        "INSTRUCTION TEXT",
        "EXAMPLE",
        existing_dependencies=[{"name": "libA"}, {"name": "libB"}],
        existing_technologies=[{"name": "TechX"}],
        texts=texts,
    )
    without_context = build_extraction_prompt("content here", "setup.py", "INSTRUCTION TEXT", "EXAMPLE", texts=texts)

    assert with_context == _snapshot("technology.txt")
    assert without_context == _snapshot("technology_no_context.txt")
