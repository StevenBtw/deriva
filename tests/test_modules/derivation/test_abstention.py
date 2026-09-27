"""Tests for Addition B: candidate-strength-based abstention."""

from __future__ import annotations

from deriva.modules.derivation.base import (
    Candidate,
    build_derivation_prompt,
    compute_candidate_strength,
)


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
    def test_strength_section_included_when_provided(self):
        cs = [_make_candidate(f"n{i}", pagerank_percentile=30, kcore_percentile=30) for i in range(5)]
        strength = compute_candidate_strength(cs)
        prompt = build_derivation_prompt(
            candidates=cs,
            instruction="do things",
            example="{}",
            element_type="BusinessFunction",
            strength=strength,
        )
        assert "Candidate Evidence Strength" in prompt
        assert "weak" in prompt

    def test_strength_section_omitted_when_absent(self):
        prompt = build_derivation_prompt(
            candidates=[_make_candidate()],
            instruction="do things",
            example="{}",
            element_type="BusinessFunction",
            strength=None,
        )
        assert "Candidate Evidence Strength" not in prompt

    def test_prompt_permits_empty_output_when_minimal(self):
        # Minimal-strength candidates must trigger the abstention rule.
        cs = [_make_candidate("n1", pagerank_percentile=5, kcore_percentile=5)]
        prompt = build_derivation_prompt(
            candidates=cs,
            instruction="do things",
            example="{}",
            element_type="BusinessFunction",
            strength=compute_candidate_strength(cs),
        )
        assert "empty list" in prompt.lower()

    def test_prompt_omits_abstention_rule_when_strong(self):
        # Strong-strength candidates must NOT carry the "empty list" valve —
        # otherwise the LLM over-abstains on repos with many noisy candidates.
        cs = [_make_candidate(f"n{i}", pagerank_percentile=90, kcore_percentile=90) for i in range(20)]
        prompt = build_derivation_prompt(
            candidates=cs,
            instruction="do things",
            example="{}",
            element_type="ApplicationComponent",
            strength=compute_candidate_strength(cs),
        )
        assert "empty list is a valid" not in prompt.lower()

    def test_prompt_forbids_type_suffix_in_names(self):
        prompt = build_derivation_prompt(
            candidates=[_make_candidate()],
            instruction="do things",
            example="{}",
            element_type="ApplicationComponent",
        )
        # Suffix ban must be stated, naming names of the generic ArchiMate suffixes.
        assert '" Component"' in prompt
        assert '" Service"' in prompt

    def test_no_repo_specific_leakage(self):
        """The prompt builder must not contain repo or product names."""
        # Run with generic inputs; none of the benchmark-repo names should leak.
        prompt = build_derivation_prompt(
            candidates=[_make_candidate()],
            instruction="do things",
            example="{}",
            element_type="ApplicationComponent",
            strength=compute_candidate_strength([_make_candidate()]),
        )
        for forbidden in ("lightblue", "bigdata", "cloudbased"):
            assert forbidden.lower() not in prompt.lower()
