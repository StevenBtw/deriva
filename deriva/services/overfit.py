"""Overfit scan of draft prompt texts with the local workspace scanner.

The scanner's term lists are golden element names and the held-out and development
repositories' terms, kept in local workspace files that do not ship with Deriva; so the
scan runs only where ``workspace/scripts/check_prompt_overfit.py`` exists and reports
itself unavailable elsewhere.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCANNER = Path("workspace/scripts/check_prompt_overfit.py")


def _load(scanner: Path) -> Any:
    spec = importlib.util.spec_from_file_location("check_prompt_overfit", scanner)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {scanner}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan_texts(texts: dict[str, str], scanner: str | Path = SCANNER) -> dict[str, Any]:
    """Findings per field (``instruction``, ``example``, ``params``, ...) of the texts about to be saved."""
    path = Path(scanner)
    if not path.is_file():
        return {"available": False, "findings": []}
    module = _load(path)
    terms = module.load_terms()
    findings = [{"field": field, "finding": hit} for field, text in texts.items() if text for hit in module.find(text, terms)]
    return {"available": True, "findings": findings}
