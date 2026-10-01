"""Tests for modules.derivation.business_event module."""

from __future__ import annotations

import pytest

from deriva.modules.derivation.base import Candidate
from deriva.modules.derivation.business_event import (
    EVENT_DECORATOR_PATTERNS,
    BusinessEventDerivation,
)


class TestBusinessEventDerivationInit:
    """Tests for BusinessEventDerivation initialization."""

    def test_element_type_is_business_event(self):
        """Should have BusinessEvent as element type."""
        derivation = BusinessEventDerivation()
        assert derivation.ELEMENT_TYPE == "BusinessEvent"

    def test_has_relationship_rules(self):
        """Should have outbound and inbound relationship rules defined."""
        derivation = BusinessEventDerivation()
        assert hasattr(derivation, "OUTBOUND_RULES")
        assert hasattr(derivation, "INBOUND_RULES")
        assert len(derivation.OUTBOUND_RULES) > 0
        assert len(derivation.INBOUND_RULES) > 0


class TestHasEventDecorator:
    """Tests for _has_event_decorator method."""

    def test_returns_true_for_webhook_decorator(self):
        """Should return True for webhook decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="handle_webhook",
            labels=["Method"],
            properties={"decorators": ["webhook"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_event_handler_decorator(self):
        """Should return True for event_handler decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="on_message",
            labels=["Method"],
            properties={"decorators": ["event_handler"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_celery_task_decorator(self):
        """Should return True for celery.task decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="process_task",
            labels=["Method"],
            properties={"decorators": ["celery.task"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_signal_decorator(self):
        """Should return True for signal decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="on_save",
            labels=["Method"],
            properties={"decorators": ["signal.connect"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_listener_decorator(self):
        """Should return True for listener decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="on_event",
            labels=["Method"],
            properties={"decorators": ["listener"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_subscriber_decorator(self):
        """Should return True for subscriber decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="handle_message",
            labels=["Method"],
            properties={"decorators": ["subscriber"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_consumer_decorator(self):
        """Should return True for consumer decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="consume_message",
            labels=["Method"],
            properties={"decorators": ["consumer"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_true_for_callback_decorator(self):
        """Should return True for callback decorator."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="on_complete",
            labels=["Method"],
            properties={"decorators": ["callback"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_returns_false_for_no_decorators(self):
        """Should return False when no decorators present."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="process_data",
            labels=["Method"],
            properties={},
        )
        assert derivation._has_event_decorator(candidate) is False

    def test_returns_false_for_empty_decorators(self):
        """Should return False when decorators list is empty."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="process_data",
            labels=["Method"],
            properties={"decorators": []},
        )
        assert derivation._has_event_decorator(candidate) is False

    def test_returns_false_for_non_event_decorators(self):
        """Should return False for non-event decorators."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="get_data",
            labels=["Method"],
            properties={"decorators": ["cached", "route", "property"]},
        )
        assert derivation._has_event_decorator(candidate) is False

    def test_handles_non_string_decorators(self):
        """Should handle non-string items in decorators list."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="mixed_handler",
            labels=["Method"],
            properties={"decorators": [None, 123, "event_handler"]},
        )
        assert derivation._has_event_decorator(candidate) is True

    def test_case_insensitive_matching(self):
        """Should match decorators case-insensitively."""
        derivation = BusinessEventDerivation()
        candidate = Candidate(
            node_id="1",
            name="handler",
            labels=["Method"],
            properties={"decorators": ["WEBHOOK_HANDLER"]},
        )
        assert derivation._has_event_decorator(candidate) is True


class TestConceptCandidates:
    """Business concepts were chosen by the query: the method patterns and pagerank threshold do not apply to them."""

    @staticmethod
    def _concept(node_id, name):
        return Candidate(node_id=node_id, name=name, labels=["Graph", "BusinessConcept"], properties={"conceptTypes": ["event"], "confidence": 0.9})

    def test_concepts_pass_in_query_order_up_to_the_cap(self):
        concepts = [self._concept("c3", "Gamma"), self._concept("c1", "Alpha"), self._concept("c2", "Beta")]

        # A pagerank far below the method threshold does not matter for concepts
        low = {c.node_id: {"pagerank": 0.0001} for c in concepts}

        result = BusinessEventDerivation().filter_candidates(candidates=concepts, enrichments=low, max_candidates=2, include_patterns={"event"}, exclude_patterns=set())

        assert [c.node_id for c in result] == ["c3", "c1"]

    def test_methods_keep_the_method_path(self):
        method = Candidate(node_id="m1", name="helper", labels=["Graph", "Method"], properties={})
        low = {"m1": {"pagerank": 0.0001}}

        result = BusinessEventDerivation().filter_candidates(candidates=[method], enrichments=low, max_candidates=10, include_patterns={"event"}, exclude_patterns=set())

        assert result == []  # below the method pagerank threshold, matching no event pattern

    def test_a_method_among_the_concepts_does_not_change_their_path(self):
        concepts = [self._concept("c2", "Beta"), self._concept("c1", "Alpha")]
        method = Candidate(node_id="m1", name="helper", labels=["Graph", "Method"], properties={})
        low = {n: {"pagerank": 0.0001} for n in ("c1", "c2", "m1")}

        candidates = [concepts[0], method, concepts[1]]

        result = BusinessEventDerivation().filter_candidates(candidates=candidates, enrichments=low, max_candidates=10, include_patterns={"event"}, exclude_patterns=set())

        # The concepts keep their query order; the method still meets the method threshold
        assert [c.node_id for c in result] == ["c2", "c1"]

    @pytest.mark.parametrize("cap, expected", [(10, ["c2", "c1", "d1", "p1"]), (3, ["c2", "c1", "d1"])])
    def test_concepts_come_first_then_decorated_then_pattern_methods(self, cap, expected):
        concepts = [self._concept("c2", "Beta"), self._concept("c1", "Alpha")]
        decorated = Candidate(node_id="d1", name="on_order", labels=["Graph", "Method"], properties={"decorators": ["webhook"]})
        matching = Candidate(node_id="p1", name="order_event", labels=["Graph", "Method"], properties={})
        high = {n: {"pagerank": 0.5} for n in ("c1", "c2", "d1", "p1")}
        candidates = [matching, concepts[0], decorated, concepts[1]]

        result = BusinessEventDerivation().filter_candidates(candidates=candidates, enrichments=high, max_candidates=cap, include_patterns={"event"}, exclude_patterns=set())

        assert [c.node_id for c in result] == expected


class TestFilterCandidates:
    """Tests for filter_candidates method."""

    def test_sets_event_decorator_property(self):
        """Should set has_event_decorator property on event candidates."""
        derivation = BusinessEventDerivation()
        candidates = [
            Candidate(
                node_id="1",
                name="event_handler",
                labels=["Method"],
                properties={"decorators": ["webhook"]},
                pagerank=0.5,
            ),
        ]
        enrichments = {"1": {"pagerank": 0.5}}

        result = derivation.filter_candidates(
            candidates=candidates,
            enrichments=enrichments,
            max_candidates=10,
            include_patterns=set(),
            exclude_patterns=set(),
        )

        # Check that decorator property is set
        if result:
            assert any(c.properties.get("has_event_decorator") for c in result)

    def test_filters_empty_names(self):
        """Should filter out candidates with empty names."""
        derivation = BusinessEventDerivation()
        candidates = [
            Candidate(
                node_id="1",
                name="",
                labels=["Method"],
                properties={},
                pagerank=0.5,
            ),
            Candidate(
                node_id="2",
                name="valid_handler",
                labels=["Method"],
                properties={},
                pagerank=0.5,
            ),
        ]
        enrichments = {"1": {"pagerank": 0.5}, "2": {"pagerank": 0.5}}

        result = derivation.filter_candidates(
            candidates=candidates,
            enrichments=enrichments,
            max_candidates=10,
            include_patterns=set(),
            exclude_patterns=set(),
        )

        # Only valid name should pass
        assert all(c.name for c in result)

    def test_respects_max_candidates(self):
        """Should respect max_candidates limit."""
        derivation = BusinessEventDerivation()
        candidates = [
            Candidate(
                node_id=str(i),
                name=f"on_event_{i}",
                labels=["Method"],
                properties={},
                pagerank=0.5,
            )
            for i in range(20)
        ]
        enrichments = {str(i): {"pagerank": 0.5} for i in range(20)}

        result = derivation.filter_candidates(
            candidates=candidates,
            enrichments=enrichments,
            max_candidates=5,
            include_patterns={"on_"},
            exclude_patterns=set(),
        )

        assert len(result) <= 5


class TestConstants:
    """Tests for module constants."""

    def test_event_decorator_patterns_has_common_patterns(self):
        """Should include common event decorator patterns."""
        assert "webhook" in EVENT_DECORATOR_PATTERNS
        assert "event" in EVENT_DECORATOR_PATTERNS
        assert "signal" in EVENT_DECORATOR_PATTERNS
        assert "listener" in EVENT_DECORATOR_PATTERNS
        assert "celery" in EVENT_DECORATOR_PATTERNS
        assert "callback" in EVENT_DECORATOR_PATTERNS
