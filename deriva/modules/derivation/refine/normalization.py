"""
Dedup-focused name normalization.

Applied on top of base.normalize_name() for the duplicate_elements step
to collapse ArchiMate-specific naming drift (type-name suffixes, repo-name
prefixes, case variants) that the generic text normalization does not catch.

DESIGN INVARIANT: no repo-specific hardcoded inputs. No product names, tech
stacks, or per-repo configuration. All inputs are either ArchiMate-generic
constants or runtime context derived from the current graph (the repo name).
Rules that cannot be expressed generically do not belong in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    "command",
)


@dataclass
class RepoContext:
    """Runtime context for dedup normalization.

    Populated from the current graph, not from static config. An empty
    context (no repo name) is valid and makes the repo-specific rules no-ops.
    """

    repo_name: str = ""


def strip_archimate_suffix(name: str) -> str:
    """Remove a trailing ArchiMate type suffix if present.

    Examples:
        'Storage Controller' -> 'Storage'
        'Order API' -> 'Order'
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
    """Remove the leading tokens that spell the repo name (case-insensitive).

    Repo name is compared with separators stripped, so a hyphenated or
    mixed-case repo name matches its prefix regardless of formatting, also
    when it is spread over several words ("Tea Store Registry" for TeaStore).
    A name that is only the repo name stays.
    """
    if not name or not repo_name:
        return name
    repo_normalized = re.sub(r"[-_\s]+", "", repo_name).lower()
    if not repo_normalized:
        return name
    tokens = name.split()
    joined = ""
    for i, token in enumerate(tokens[:-1]):
        joined += re.sub(r"[-_]+", "", token).lower()
        if joined == repo_normalized:
            return " ".join(tokens[i + 1 :])
        if not repo_normalized.startswith(joined):
            break
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
