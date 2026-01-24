"""
BusinessActor Derivation.

A BusinessActor represents a business entity that is capable of performing
behavior. This includes users, roles, departments, or external parties.

Graph signals:
- TypeDefinition nodes with user/role/actor patterns
- BusinessConcept nodes representing people or organizations
- Authentication/authorization related code
- Route handlers with user context
- Auth-decorated methods (permission checks, role requirements)

Filtering strategy:
1. Query TypeDefinition and BusinessConcept nodes
2. Detect auth-related decorators (@login_required, @permission, @role, etc.)
3. Filter for actor/role/user patterns
4. Exclude technical/utility classes
5. Focus on entities that perform actions

LLM role:
- Identify which types represent actors
- Generate meaningful actor names
- Write documentation describing the actor's role

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessActor

Typical Sources:
    - TypeDefinition nodes (User, Role, Admin, Customer classes)
    - BusinessConcept nodes representing organizational roles
    - Methods with auth/permission decorators (indicate actor context)
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

# Decorators that indicate authentication/authorization (actor context)
AUTH_DECORATOR_PATTERNS = {
    "auth",
    "login",
    "permission",
    "role",
    "require",
    "admin",
    "user",
    "staff",
    "owner",
    "access",
    "protected",
    "secure",
    "jwt",
    "token",
    "session",
}

# Name patterns that suggest actor types
ACTOR_NAME_PATTERNS = {
    "user",
    "role",
    "admin",
    "customer",
    "client",
    "agent",
    "operator",
    "manager",
    "owner",
    "member",
    "participant",
    "stakeholder",
    "account",
    "profile",
    "principal",
    "identity",
}


class BusinessActorDerivation(HybridDerivation):
    """
    BusinessActor element derivation.

    Uses hybrid filtering combining patterns, auth decorator detection,
    and graph analysis to identify business actors.

    Auth pattern detection: Types or methods with @login_required,
    @permission_required, @role_required, etc. are prioritized as
    they indicate actor-related functionality.
    """

    ELEMENT_TYPE = "BusinessActor"

    # Graph filtering configuration
    MIN_PAGERANK = 0.001

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Assignment",
            description="Business actors perform business processes",
        ),
        RelationshipRule(
            target_type="BusinessFunction",
            rel_type="Assignment",
            description="Business actors perform business functions",
        ),
        RelationshipRule(
            target_type="ApplicationInterface",
            rel_type="Serving",
            description="Business actors use application interfaces",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = []

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
        Filter candidates for BusinessActor derivation.

        Strategy depends on source type:
        - BusinessConcept: Filter by confidence (already semantically identified)
        - TypeDefinition: Original auth/pattern-based filtering
        """
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        for c in candidates:
            enrich_candidate(c, enrichments)

        # Check if candidates are BusinessConcept (have conceptType property)
        is_business_concept = any(
            "BusinessConcept" in c.labels or c.properties.get("conceptType")
            for c in candidates
        )

        if is_business_concept:
            # BusinessConcept source: filter by confidence, skip graph metrics
            return self._filter_business_concepts(candidates, max_candidates)

        # TypeDefinition source: original auth/pattern-based filtering
        return self._filter_typedef_candidates(
            candidates, enrichments, max_candidates, include_patterns, exclude_patterns
        )

    def _filter_business_concepts(
        self,
        candidates: list[Candidate],
        max_candidates: int,
    ) -> list[Candidate]:
        """Filter BusinessConcept candidates by confidence.

        BusinessConcepts are already semantically identified as actors,
        so we just filter by confidence and limit count.
        """
        MIN_CONFIDENCE = 0.7

        filtered = []
        for c in candidates:
            confidence = c.properties.get("confidence", 0)
            if confidence >= MIN_CONFIDENCE:
                filtered.append(c)

        # Sort by confidence descending
        filtered.sort(key=lambda c: c.properties.get("confidence", 0), reverse=True)

        self.logger.debug(
            "BusinessActor filter (BusinessConcept): %d total -> %d passed confidence >= %.1f",
            len(candidates),
            len(filtered),
            MIN_CONFIDENCE,
        )

        return filtered[:max_candidates]

    def _filter_typedef_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str],
        exclude_patterns: set[str],
    ) -> list[Candidate]:
        """Filter TypeDefinition candidates using auth/pattern detection.

        Original strategy:
        1. Detect auth-related decorators (@login_required, @permission, etc.)
        2. Check for actor-related name patterns
        3. Apply pattern matching from config
        4. Apply graph filtering (PageRank threshold)
        """
        filtered = [c for c in candidates if c.name]

        # Group candidates by signal strength
        auth_decorated = []
        actor_named = []
        pattern_matched = []
        others = []

        for c in filtered:
            has_auth = self._has_auth_decorator(c)
            has_actor_name = self._has_actor_name_pattern(c.name)
            matches_config = self.matches_patterns(
                c.name, include_patterns, exclude_patterns
            )

            if has_auth:
                c.properties["has_auth_decorator"] = True
                auth_decorated.append(c)
            elif has_actor_name:
                c.properties["has_actor_name"] = True
                actor_named.append(c)
            elif matches_config:
                pattern_matched.append(c)
            else:
                others.append(c)

        # Apply graph filtering to each group
        auth_decorated = self.apply_graph_filtering(
            auth_decorated, enrichments, max_candidates // 4
        )
        actor_named = self.apply_graph_filtering(
            actor_named, enrichments, max_candidates // 4
        )
        pattern_matched = self.apply_graph_filtering(
            pattern_matched, enrichments, max_candidates // 4
        )

        # Combine: auth-decorated first, then actor-named, then pattern-matched, then others
        combined = auth_decorated + actor_named + pattern_matched

        remaining_slots = max_candidates - len(combined)
        if remaining_slots > 0 and others:
            others = self.apply_graph_filtering(others, enrichments, remaining_slots)
            combined.extend(others)

        self.logger.debug(
            "BusinessActor filter (TypeDefinition): %d total -> %d auth, %d actor-named, %d pattern -> %d final",
            len(candidates),
            len(auth_decorated),
            len(actor_named),
            len(pattern_matched),
            len(combined),
        )

        return combined[:max_candidates]

    def _has_auth_decorator(self, candidate: Candidate) -> bool:
        """Check if candidate has auth-related decorators.

        Looks for decorators like @login_required, @permission_required,
        @role_required, @admin_only, etc.

        Args:
            candidate: The candidate to check

        Returns:
            True if any auth-related decorator is found
        """
        decorators = candidate.properties.get("decorators", [])
        if not decorators:
            return False

        for decorator in decorators:
            if not isinstance(decorator, str):
                continue
            decorator_lower = decorator.lower()
            for pattern in AUTH_DECORATOR_PATTERNS:
                if pattern in decorator_lower:
                    return True

        return False

    def _has_actor_name_pattern(self, name: str) -> bool:
        """Check if name contains actor-related patterns.

        Args:
            name: The candidate name to check

        Returns:
            True if name suggests an actor type
        """
        if not name:
            return False

        name_lower = name.lower()
        for pattern in ACTOR_NAME_PATTERNS:
            if pattern in name_lower:
                return True

        return False
