"""
BusinessEvent Derivation.

A BusinessEvent represents an organizational state change. Events may originate
from the environment (e.g., customers), or be triggered by services, processes,
or other events.

Graph signals:
- Event handler methods (on*, handle*, emit*, trigger*)
- Message/event classes and types
- Callback functions
- Signal definitions
- Webhook handlers (decorator detection)
- Message queue consumers

Filtering strategy:
1. Query Method and TypeDefinition nodes
2. Detect event-related decorators (webhook, event, signal, celery, etc.)
3. Filter for event/handler patterns
4. Exclude utility event handlers
5. Focus on business-relevant events

LLM role:
- Identify which handlers represent business events
- Generate meaningful event names
- Write documentation describing the event trigger and impact

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessEvent

Typical Sources:
    - Method nodes with event handler patterns (on_*, handle_*)
    - Event class definitions and signal handlers
    - Webhook endpoints and message queue consumers
"""

from __future__ import annotations

import logging
from typing import Any

from deriva.modules.derivation.base import (
    Candidate,
    RelationshipRule,
    enrich_candidate,
)
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)

# Decorators that indicate event handlers
EVENT_DECORATOR_PATTERNS = {
    "webhook",
    "event",
    "signal",
    "listener",
    "subscriber",
    "consumer",
    "handler",
    "celery",
    "task",
    "callback",
    "on_",
    "receive",
    "message",
}


class BusinessEventDerivation(HybridDerivation):
    """
    BusinessEvent element derivation.

    Uses hybrid filtering combining patterns, decorator detection, and
    graph analysis to identify business events from event handlers.

    Decorator detection: Methods with @webhook, @event, @signal, @listener,
    @celery.task, etc. are prioritized as event handlers.
    """

    ELEMENT_TYPE = "BusinessEvent"

    # Graph filtering configuration
    MIN_PAGERANK = 0.0005

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Triggering",
            description="Business events trigger business processes",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Triggering",
            description="Business processes trigger business events",
        ),
    ]

    def filter_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str] | None = None,
        exclude_patterns: set[str] | None = None,
        **kwargs: Any,
    ) -> list[Candidate]:
        """
        Filter candidates for BusinessEvent derivation.

        Strategy:
        1. Enrich with graph metrics
        2. Detect event-related decorators (webhook, event, signal, etc.)
        3. Filter by event patterns
        4. Apply graph filtering (PageRank threshold)
        5. Prioritize decorator-detected handlers in final selection
        """
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        for c in candidates:
            enrich_candidate(c, enrichments)

        filtered = [c for c in candidates if c.name]

        # Business concepts were chosen by the query: no method patterns or pagerank threshold
        # apply to them; they keep the query order up to the cap
        if filtered and all("BusinessConcept" in c.labels for c in filtered):
            return filtered[:max_candidates]

        # Detect event handlers from decorators
        decorator_handlers = []
        non_decorator = []
        for c in filtered:
            if self._has_event_decorator(c):
                c.properties["has_event_decorator"] = True
                decorator_handlers.append(c)
            else:
                non_decorator.append(c)

        # Apply pattern matching to non-decorator candidates
        likely_events = [c for c in non_decorator if self.matches_patterns(c.name, include_patterns, exclude_patterns)]
        others = [c for c in non_decorator if not self.matches_patterns(c.name, include_patterns, exclude_patterns)]

        # Apply graph filtering to each group
        decorator_handlers = self.apply_graph_filtering(decorator_handlers, enrichments, max_candidates // 3)
        likely_events = self.apply_graph_filtering(likely_events, enrichments, max_candidates // 3)

        # Combine: decorator handlers first, then pattern-matched, then others
        combined = decorator_handlers + likely_events

        remaining_slots = max_candidates - len(combined)
        if remaining_slots > 0 and others:
            others = self.apply_graph_filtering(others, enrichments, remaining_slots)
            combined.extend(others)

        self.logger.debug(
            "BusinessEvent filter: %d total -> %d decorator, %d pattern -> %d final",
            len(candidates),
            len(decorator_handlers),
            len(likely_events),
            len(combined),
        )

        return combined[:max_candidates]

    def _has_event_decorator(self, candidate: Candidate) -> bool:
        """Check if candidate has event-related decorators.

        Looks for decorators like @webhook, @event_handler, @celery.task,
        @signal.connect, @on_message, etc.

        Args:
            candidate: The candidate to check

        Returns:
            True if any event-related decorator is found
        """
        decorators = candidate.properties.get("decorators", [])
        if not decorators:
            return False

        for decorator in decorators:
            if not isinstance(decorator, str):
                continue
            decorator_lower = decorator.lower()
            for pattern in EVENT_DECORATOR_PATTERNS:
                if pattern in decorator_lower:
                    return True

        return False
