"""Exact prompt strings, pinned while prompt text moves from code into versioned config.

Moving text must not change what the LLM receives (same prompt, same cache key,
same model). Each snapshot was captured from the prompt builder before the move.
"""

from __future__ import annotations

import json
from pathlib import Path

from deriva.modules.derivation.base import (
    Candidate,
    ElementPrompt,
    RelationshipRule,
    build_derivation_prompt,
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
        persona="You are deriving ArchiMate 3.2 relationships for newly created {element_type} elements.",
    )

    assert prompt == _snapshot("unified_relationship.txt")


def test_single_candidate_prompt_is_unchanged():
    cand = Candidate(node_id="n9", name="Cand", labels=["Graph", "Method"], properties={"x": 1})

    prompt = build_single_candidate_prompt(
        cand,
        "INSTRUCTION TEXT",
        rules=_snapshot("per_candidate_rules_BusinessProcess.txt"),
        persona="You are naming ONE candidate node as an ArchiMate BusinessProcess.",
    )

    assert prompt == _snapshot("single_candidate.txt")


def test_element_batch_prompt_is_unchanged():
    """With its row's params.prompt texts, the batch element prompt is the prompt the code built before the move."""
    texts = ElementPrompt(**json.loads(_snapshot("derivation_prompt_BusinessObject.json"))["prompt"])
    candidates = [
        Candidate(node_id="concept::r::ledger", name="Ledger", labels=["Graph", "BusinessConcept"], properties={"conceptName": "Ledger", "conceptType": "entity"}, pagerank=0.0123),
        Candidate(node_id="concept::r::journal", name="Journal", labels=["Graph", "BusinessConcept"], properties={"conceptName": "Journal"}, pagerank=0.004),
    ]
    common = {"candidates": candidates, "instruction": "Derive business objects from the candidates.", "example": '{"elements": []}', "prompt": texts}

    minimal = build_derivation_prompt(**common, strength={"count": 2, "avg_pagerank_percentile": 10.0, "avg_kcore_percentile": 5.0, "strength_label": "minimal"})
    moderate = build_derivation_prompt(**common, strength={"count": 12, "avg_pagerank_percentile": 55.0, "avg_kcore_percentile": 45.0, "strength_label": "moderate"})

    assert minimal == _snapshot("derivation_batch_minimal.txt")
    assert moderate == _snapshot("derivation_batch_moderate.txt")


def test_extraction_prompts_are_unchanged():
    """With their rows' params.prompt texts (persona and task), the four extraction prompts are the ones the code built before the move."""
    from deriva.modules.extraction import external_dependency, method, type_definition
    from deriva.modules.extraction import test as test_extraction

    texts = json.loads(_snapshot("extraction_prompts.json"))
    content = "class Ledger:\n    def post(self, entry):\n        return entry\n"

    assert type_definition.build_extraction_prompt(content, "src/ledger.alpha", "INSTRUCTION", '{"types": []}', texts["TypeDefinition"]) == _snapshot(
        "extraction_type_definition.txt"
    )
    assert method.build_extraction_prompt(content, "Ledger", "class", "src/ledger.alpha", "INSTRUCTION", '{"methods": []}', texts["Method"]) == _snapshot("extraction_method.txt")
    assert test_extraction.build_extraction_prompt(content, "tests/test_ledger.alpha", "INSTRUCTION", '{"tests": []}', texts["Test"]) == _snapshot("extraction_test.txt")
    assert external_dependency.build_extraction_prompt(content, "deps.alpha", "INSTRUCTION", '{"dependencies": []}', texts["ExternalDependency"]) == _snapshot(
        "extraction_external_dependency.txt"
    )
