"""
Base utilities for refine phase modules.

Provides shared types, utilities, and the refine step registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)


@dataclass
class RefineResult:
    """Result of a refine step execution."""

    success: bool
    step_name: str
    elements_disabled: int = 0
    elements_merged: int = 0
    relationships_deleted: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "success": self.success,
            "step_name": self.step_name,
            "elements_disabled": self.elements_disabled,
            "elements_merged": self.elements_merged,
            "relationships_deleted": self.relationships_deleted,
            "issues_found": self.issues_found,
            "issues_fixed": self.issues_fixed,
            "details": self.details,
            "errors": self.errors,
        }


class RefineStep(Protocol):
    """Protocol for refine step implementations."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute the refine step.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Optional manager for source graph operations
            llm_query_fn: Optional LLM function for semantic operations
            params: Optional step-specific parameters

        Returns:
            RefineResult with execution details
        """
        ...


# Registry of refine step implementations
REFINE_STEPS: dict[str, type] = {}


def register_refine_step(name: str):
    """Decorator to register a refine step implementation."""

    def decorator(cls: type) -> type:
        REFINE_STEPS[name] = cls
        return cls

    return decorator


def run_refine_step(
    step_name: str,
    archimate_manager: ArchimateManager,
    graph_manager: GraphManager | None = None,
    llm_query_fn: Any | None = None,
    params: dict[str, Any] | None = None,
) -> RefineResult:
    """Run a registered refine step by name.

    Args:
        step_name: Name of the refine step to run
        archimate_manager: Manager for ArchiMate model operations
        graph_manager: Optional manager for source graph operations
        llm_query_fn: Optional LLM function for semantic operations
        params: Optional step-specific parameters

    Returns:
        RefineResult with execution details
    """
    if step_name not in REFINE_STEPS:
        return RefineResult(
            success=False,
            step_name=step_name,
            errors=[f"Unknown refine step: {step_name}"],
        )

    step_class = REFINE_STEPS[step_name]
    step_instance = step_class()

    try:
        return step_instance.run(
            archimate_manager=archimate_manager,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
            params=params,
        )
    except Exception as e:
        logger.exception(f"Error running refine step {step_name}: {e}")
        return RefineResult(
            success=False,
            step_name=step_name,
            errors=[str(e)],
        )


def lemmatize_word(word: str) -> str:
    """Simple rule-based lemmatizer for English words.

    Reduces words to base form without heavy NLP dependencies.
    Handles common verb and noun suffixes used in software/architecture terms.
    """
    if len(word) <= 3:
        return word

    # Verb suffixes (order matters - check longer suffixes first)
    verb_rules = [
        ("ating", "ate"),  # generating → generate
        ("iting", "it"),  # editing → edit
        ("eting", "ete"),  # deleting → delete
        ("izing", "ize"),  # initializing → initialize
        ("ying", "y"),  # modifying → modify
        ("ting", "t"),  # getting → get (but not "ting" words)
        ("ning", "n"),  # running → run
        ("ming", "m"),  # programming → program
        ("ping", "p"),  # mapping → map
        ("ding", "d"),  # loading → load
        ("bing", "b"),  # grabbing → grab
        ("ging", "g"),  # logging → log
        ("sing", "se"),  # parsing → parse
        ("ing", ""),  # processing → process (fallback)
        ("ation", "ate"),  # generation → generate
        ("ition", "it"),  # addition → add (approximate)
        ("tion", "t"),  # creation → create
        ("sion", "de"),  # decision → decide (approximate)
        ("ment", ""),  # management → manage
        ("ence", ""),  # preference → prefer
        ("ance", ""),  # performance → perform
        ("ness", ""),  # completeness → complete
        ("able", ""),  # readable → read
        ("ible", ""),  # visible → vis (approximate)
        ("ful", ""),  # successful → success
        ("less", ""),  # stateless → state
        ("ive", ""),  # active → act
        ("ous", ""),  # continuous → continu
        ("ical", ""),  # technical → techn
        ("al", ""),  # original → origin
        ("ed", ""),  # created → create
        ("er", ""),  # handler → handle
        ("or", ""),  # processor → process
        ("ly", ""),  # quickly → quick
    ]

    # Noun plural rules
    noun_rules = [
        ("ies", "y"),  # entries → entry, categories → category
        ("ves", "f"),  # leaves → leaf
        ("es", ""),  # processes → process, classes → class
        ("s", ""),  # items → item (fallback)
    ]

    original = word

    # Try verb rules first (for action words)
    for suffix, replacement in verb_rules:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            candidate = word[: -len(suffix)] + replacement
            if len(candidate) >= 3:
                return candidate

    # Try noun plural rules
    for suffix, replacement in noun_rules:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            candidate = word[: -len(suffix)] + replacement
            if len(candidate) >= 3:
                return candidate

    return original


def normalize_name(
    name: str,
    extra_synonyms: dict[str, str] | None = None,
    use_lemmatization: bool = False,
) -> str:
    """Normalize element name for comparison.

    Converts to lowercase, removes common prefixes/suffixes,
    normalizes whitespace, and applies synonym mappings.

    Args:
        name: The element name to normalize
        extra_synonyms: Optional additional synonyms to apply (merged with defaults)
        use_lemmatization: If True, apply rule-based lemmatization before synonyms
    """
    if not name:
        return ""

    normalized = name.lower().strip()
    # Remove common prefixes
    for prefix in ["the ", "a ", "an "]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    # Normalize whitespace and separators
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())

    # Default synonyms - generic ArchiMate/software architecture equivalents
    # Based on ArchiMate naming conventions and iSAQB glossary
    # See: https://github.com/AlbertoDMendoza/ArchiMateBestPractices
    # See: https://leanpub.com/isaqbglossary/read
    synonyms = {
        # === ACTION VERBS (behavioral elements use verb phrases) ===
        "insert": "create",
        "add": "create",
        "new": "create",
        "remove": "delete",
        "destroy": "delete",
        "modify": "update",
        "edit": "update",
        "change": "update",
        "fetch": "get",
        "retrieve": "get",
        "obtain": "get",
        "send": "transmit",
        "submit": "transmit",
        "receive": "accept",
        "validate": "verify",
        "check": "verify",
        # === PLURALS TO SINGULAR (structural elements use singular nouns) ===
        "details": "detail",
        "items": "item",
        "services": "service",
        "components": "component",
        "objects": "object",
        "processes": "process",
        "functions": "function",
        "events": "event",
        "actors": "actor",
        "interfaces": "interface",
        "nodes": "node",
        "devices": "device",
        "artifacts": "artifact",
        "elements": "element",
        "assets": "asset",
        "resources": "resource",
        "positions": "position",
        "invoices": "invoice",
        "orders": "order",
        "customers": "customer",
        "users": "user",
        "products": "product",
        "payments": "payment",
        "transactions": "transaction",
        "records": "record",
        "entries": "entry",
        "messages": "message",
        "requests": "request",
        "responses": "response",
        "templates": "template",
        "configurations": "configuration",
        "settings": "setting",
        "properties": "property",
        "attributes": "attribute",
        "parameters": "parameter",
        "values": "value",
        "types": "type",
        "categories": "category",
        "classes": "class",
        "modules": "module",
        "packages": "package",
        "files": "file",
        "documents": "document",
        "reports": "report",
        "logs": "log",
        # === ABBREVIATION NORMALIZATION ===
        "config": "configuration",
        "configs": "configuration",
        "cfg": "configuration",
        "app": "application",
        "apps": "application",
        "db": "database",
        "dbs": "database",
        "datastore": "database",
        "repo": "repository",
        "repos": "repository",
        "auth": "authentication",
        "authz": "authorization",
        "authn": "authentication",
        "msg": "message",
        "msgs": "message",
        "req": "request",
        "res": "response",
        "resp": "response",
        "doc": "document",
        "docs": "document",
        "info": "information",
        "mgmt": "management",
        "mgr": "manager",
        "svc": "service",
        "svcs": "service",
        "util": "utility",
        "utils": "utility",
        "lib": "library",
        "libs": "library",
        "api": "interface",
        "apis": "interface",
        # === COMPONENT/STRUCTURE SYNONYMS ===
        "subsystem": "component",
        "building block": "component",
        "block": "component",
        # === PROCESS/HANDLING SYNONYMS ===
        "handling": "processing",
        "handler": "processor",
        "handle": "process",
        "workflow": "process",
        "procedure": "process",
        "routine": "process",
        # === DOCUMENT/RENDERING SYNONYMS ===
        "generation": "rendering",
        "generator": "renderer",
        "generate": "render",
        # === BUSINESS TERM CANONICALIZATION ===
        "client": "customer",
        "buyer": "customer",
        "account": "customer",
        "purchaser": "customer",
        "purchase": "order",
        "sale": "order",
        "lineitem": "position",
        "line item": "position",
        "orderline": "position",
        "order line": "position",
    }

    # Merge with extra synonyms (extra takes precedence)
    if extra_synonyms:
        synonyms = {**synonyms, **extra_synonyms}

    words = normalized.split()

    # Apply lemmatization if enabled (before synonym lookup)
    if use_lemmatization:
        words = [lemmatize_word(word) for word in words]

    # Apply synonym mapping
    normalized_words = [synonyms.get(word, word) for word in words]
    return " ".join(normalized_words)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1.0 - (distance / max_len)
