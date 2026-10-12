"""What this installation is: home folder, workspace, version and optional parts (for the CLI and the studio, which import services only)."""

from __future__ import annotations

import importlib.util
from importlib.metadata import version as _distribution_version
from pathlib import Path

from deriva.common import paths, settings

# The distribution that carries the version (the root project; all three packages share it)
DISTRIBUTION = "deriva-cli"


def home() -> Path:
    """The Deriva home folder (.env, workspace and, outside a checkout, the config database)."""
    return paths.home()


def workspace() -> Path:
    return paths.workspace()


def features() -> dict[str, bool]:
    """The optional parts of this installation: benchmarking ships only in deriva-dev."""
    return {"benchmark": importlib.util.find_spec("deriva.bench") is not None}


def version() -> str:
    """The installed Deriva version (all three packages share it)."""
    return _distribution_version(DISTRIBUTION)


def suppress_pydantic_ai_banner() -> None:
    """Keep pydantic-ai's first-run banner out of the CLI's and the studio's output."""
    settings.suppress_pydantic_ai_banner()
