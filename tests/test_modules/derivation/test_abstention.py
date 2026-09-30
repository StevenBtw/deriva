"""Tests for Addition B: candidate-strength-based abstention."""

from __future__ import annotations

from deriva.modules.derivation.base import (
    Candidate,
    ElementPrompt,
    build_derivation_prompt,
    compute_candidate_strength,
)

PROMPT = ElementPrompt(persona="PERSONA", candidates="CANDIDATES NOTE", rules="1. FIRST\n{abstention}3. THIRD", abstention="2. ABSTAIN\n")


def _make_candidate(
    node_id: str = "n1",
    pagerank_percentile: float = 0.0,
    kcore_percentile: float = 0.0,
) -> Candidate:
    return Candidate(
        node_id=node_id,
        name=node_id,
        pagerank_percentile=pagerank_percentile,
        kcore_percentile=kcore_percentile,
    )


class TestComputeCandidateStrength:
    def test_empty_is_minimal(self):
        s = compute_candidate_strength([])
        assert s["count"] == 0
        assert s["strength_label"] == "minimal"

    def test_single_weak_candidate_is_minimal(self):
        s = compute_candidate_strength([_make_candidate(pagerank_percentile=10, kcore_percentile=10)])
        assert s["count"] == 1
        assert s["strength_label"] == "minimal"

    def test_few_weak_candidates_are_weak(self):
        cs = [_make_candidate(f"n{i}", pagerank_percentile=30, kcore_percentile=30) for i in range(5)]
        s = compute_candidate_strength(cs)
        assert s["strength_label"] == "weak"

    def test_many_moderate_candidates_are_moderate(self):
        cs = [_make_candidate(f"n{i}", pagerank_percentile=55, kcore_percentile=55) for i in range(10)]
        s = compute_candidate_strength(cs)
        assert s["strength_label"] == "moderate"

    def test_strong_candidates(self):
        cs = [_make_candidate(f"n{i}", pagerank_percentile=85, kcore_percentile=85) for i in range(10)]
        s = compute_candidate_strength(cs)
        assert s["strength_label"] == "strong"

    def test_mixed_averages_correctly(self):
        cs = [
            _make_candidate("a", pagerank_percentile=90, kcore_percentile=90),
            _make_candidate("b", pagerank_percentile=10, kcore_percentile=10),
        ]
        s = compute_candidate_strength(cs)
        # n=2 triggers "minimal" regardless of average
        assert s["strength_label"] == "minimal"
        assert s["avg_pagerank_percentile"] == 50.0


class TestAbstentionPrompt:
    """The builder places the step's configured texts (params.prompt); the abstention text only when the evidence is minimal."""

    def test_strength_section_included_when_provided(self):
        cs = [_make_candidate(f"n{i}", pagerank_percentile=30, kcore_percentile=30) for i in range(5)]
        prompt = build_derivation_prompt(candidates=cs, instruction="do things", example="{}", prompt=PROMPT, strength=compute_candidate_strength(cs))

        assert "Candidate Evidence Strength" in prompt
        assert "weak" in prompt

    def test_strength_section_omitted_when_absent(self):
        prompt = build_derivation_prompt(candidates=[_make_candidate()], instruction="do things", example="{}", prompt=PROMPT, strength=None)

        assert "Candidate Evidence Strength" not in prompt

    def test_the_abstention_text_fills_its_slot_when_minimal(self):
        cs = [_make_candidate("n1", pagerank_percentile=5, kcore_percentile=5)]
        prompt = build_derivation_prompt(candidates=cs, instruction="do things", example="{}", prompt=PROMPT, strength=compute_candidate_strength(cs))

        assert "1. FIRST\n2. ABSTAIN\n3. THIRD" in prompt

    def test_the_slot_stays_empty_when_the_evidence_is_strong(self):
        # Otherwise the LLM over-abstains on repos with many noisy candidates
        cs = [_make_candidate(f"n{i}", pagerank_percentile=90, kcore_percentile=90) for i in range(20)]
        prompt = build_derivation_prompt(candidates=cs, instruction="do things", example="{}", prompt=PROMPT, strength=compute_candidate_strength(cs))

        assert "1. FIRST\n3. THIRD" in prompt
        assert "ABSTAIN" not in prompt

    def test_the_configured_texts_are_placed(self):
        prompt = build_derivation_prompt(candidates=[_make_candidate()], instruction="do things", example="{}", prompt=PROMPT)

        assert prompt.startswith("PERSONA\n\n## Instructions\ndo things")
        assert "## Candidate Nodes\nCANDIDATES NOTE\n" in prompt

    def test_no_repo_specific_leakage(self):
        """The prompt builder must not contain repo or product names."""
        prompt = build_derivation_prompt(
            candidates=[_make_candidate()], instruction="do things", example="{}", prompt=PROMPT, strength=compute_candidate_strength([_make_candidate()])
        )
        for forbidden in ("lightblue", "bigdata", "cloudbased"):
            assert forbidden.lower() not in prompt.lower()
