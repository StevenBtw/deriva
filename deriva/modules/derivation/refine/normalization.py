"""
Dedup-focused name normalization.

Applied on top of base.normalize_name() for the duplicate_elements step
to collapse ArchiMate-specific naming drift (type-name suffixes, repo-name
prefixes, case variants) that the generic text normalization does not catch.

DESIGN INVARIANT: no repo-specific hardcoded inputs. No product names, tech
stacks, or per-repo configuration. All inputs are either ArchiMate-generic
constants or runtime context derived from the current graph (repo name,
derived BusinessObjects). Rules that cannot be expressed generically do not
belong in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ArchiMate element type names that the LLM tends to append as suffixes.
# These are from the ArchiMate standard, not from any specific repo.
_ARCHIMATE_TYPE_SUFFIXES = (
    "component",
    "service",
    "interface",
    "api",
    "endpoint",
    "gateway",
    "controller",
)


@dataclass
class RepoContext:
    """Runtime context for dedup normalization.

    Populated from the current graph, not from static config. An empty
    context (no repo name, no business objects) is valid and makes the
    repo-specific rules no-ops.
    """

    repo_name: str = ""
    business_objects: list[str] = field(default_factory=list)


def strip_archimate_suffix(name: str) -> str:
    """Remove a trailing ArchiMate type suffix if present.

    Examples:
        'Mongo Controller' -> 'Mongo'
        'Data REST API' -> 'Data REST'
        'User' -> 'User'  (single token, unchanged)
    """
    if not name:
        return name
    tokens = name.split()
    if len(tokens) <= 1:
        return name
    if tokens[-1].lower() in _ARCHIMATE_TYPE_SUFFIXES:
        return " ".join(tokens[:-1])
    return name


def strip_repo_prefix(name: str, repo_name: str) -> str:
    """Remove a leading token matching the repo name (case-insensitive).

    Repo name is compared with separators stripped, so a hyphenated or
    mixed-case repo name matches a prefix token regardless of formatting.
    """
    if not name or not repo_name:
        return name
    repo_normalized = re.sub(r"[-_\s]+", "", repo_name).lower()
    if not repo_normalized:
        return name
    tokens = name.split()
    if len(tokens) <= 1:
        return name
    first_normalized = re.sub(r"[-_]+", "", tokens[0]).lower()
    if first_normalized == repo_normalized:
        return " ".join(tokens[1:])
    return name


def to_title_case(name: str) -> str:
    """Simple Title Case for comparison purposes.

    Not intended for display; all-caps acronyms lose their case. The original
    name is preserved in the element; this form is only used for similarity
    matching in dedup.
    """
    if not name:
        return name
    return " ".join(word.capitalize() for word in name.split())


def normalize_for_dedup(name: str, ctx: RepoContext) -> str:
    """Return the canonical form used for dedup similarity comparison.

    The original display name is preserved on the element; this value is only
    used when deciding whether two elements should be merged.
    """
    if not name:
        return ""
    result = strip_repo_prefix(name, ctx.repo_name)
    result = strip_archimate_suffix(result)
    result = " ".join(result.split())
    result = to_title_case(result)
    return result


def collapse_bo_suffix_groups(
    names: list[str], business_objects: list[str]
) -> dict[str, str]:
    """Map names that differ only by a BusinessObject token to a shared canonical.

    Example: with business_objects=['Data', 'Likes', 'Ratings'],
    ['Aggregate Data', 'Aggregate Likes', 'Aggregate Ratings'] all map to
    'Aggregate <BO>'.

    Returns a dict from original name to canonical form. Used for
    BusinessProcess entity-suffix collapse (plan rule 4).
    """
    if not names:
        return {}
    if not business_objects:
        return {name: name for name in names}

    bo_lower = {bo.lower() for bo in business_objects}

    def mask(name: str) -> str:
        tokens = name.split()
        masked = ["<BO>" if token.lower() in bo_lower else token for token in tokens]
        return " ".join(masked)

    return {name: mask(name) for name in names}
