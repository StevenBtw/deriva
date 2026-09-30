"""NLP tool adapter: the deterministic multilingual term extraction in tools/nlp (its own Python environment)."""

from __future__ import annotations

from .manager import NlpTool, NlpToolError

__all__ = ["NlpTool", "NlpToolError"]
