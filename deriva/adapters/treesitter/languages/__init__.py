"""Language-specific tree-sitter extractors.

Each language has its own extractor class that knows how to navigate
the tree-sitter parse tree for that language.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LanguageExtractor

if TYPE_CHECKING:
    pass

# Language registry - maps language names to extractor classes
# Populated when extractors are imported
_LANGUAGE_REGISTRY: dict[str, type[LanguageExtractor]] = {}

# Flag to track if all extractors have been loaded
_EXTRACTORS_LOADED: bool = False


def get_extractor(language: str) -> LanguageExtractor | None:
    """Get an extractor instance for a language.

    Args:
        language: Language name (e.g., 'python', 'javascript')

    Returns:
        LanguageExtractor instance or None if unsupported
    """
    # Lazy import extractors to avoid loading all grammars upfront
    _ensure_extractors_loaded()

    extractor_class = _LANGUAGE_REGISTRY.get(language.lower())
    if extractor_class:
        return extractor_class()
    return None


def register_extractor(language: str, extractor_class: type[LanguageExtractor]) -> None:
    """Register a language extractor.

    Args:
        language: Language name
        extractor_class: Extractor class to register
    """
    _LANGUAGE_REGISTRY[language.lower()] = extractor_class


def supported_languages() -> list[str]:
    """Get list of supported languages."""
    _ensure_extractors_loaded()
    return list(_LANGUAGE_REGISTRY.keys())


def _ensure_extractors_loaded() -> None:
    """Lazy-load all language extractors."""
    global _EXTRACTORS_LOADED
    if _EXTRACTORS_LOADED:
        return

    # Import all extractors - they self-register on import
    try:
        from . import python  # noqa: F401
    except ImportError:
        pass

    try:
        from . import javascript  # noqa: F401
    except ImportError:
        pass

    try:
        from . import java  # noqa: F401
    except ImportError:
        pass

    try:
        from . import csharp  # noqa: F401
    except ImportError:
        pass

    # Structural extractors (no grammar package)
    from . import (
        bms,  # noqa: F401
        cobol,  # noqa: F401
        jcl,  # noqa: F401
    )

    _EXTRACTORS_LOADED = True


__all__ = [
    "LanguageExtractor",
    "get_extractor",
    "register_extractor",
    "supported_languages",
]
