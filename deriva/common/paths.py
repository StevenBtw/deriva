"""Where Deriva keeps its state: one home folder for .env, the workspace and the config database.

The home is DERIVA_HOME when set, the repository root when Deriva runs from a source
checkout, and ~/.deriva for an installed tool. DERIVA_HOME comes from the process
environment only: the .env lives inside the home, so it cannot move it.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME_VARIABLE = "DERIVA_HOME"
# deriva/common/paths.py: two levels up is the repository root in a checkout, site-packages in an installed tool
_ROOT = Path(__file__).resolve().parents[2]


def _override() -> Path | None:
    value = os.environ.get(HOME_VARIABLE, "").strip()
    return Path(value).expanduser().resolve() if value else None


def is_checkout() -> bool:
    """True when running from a source checkout without DERIVA_HOME (the checkout keeps its own layout)."""
    return _override() is None and (_ROOT / "pyproject.toml").is_file()


def home() -> Path:
    """The folder that holds .env, the workspace and, outside a checkout, the config database."""
    override = _override()
    if override is not None:
        return override
    if (_ROOT / "pyproject.toml").is_file():
        return _ROOT
    return Path.home() / ".deriva"


def env_file() -> Path:
    return home() / ".env"


def workspace() -> Path:
    return home() / "workspace"


def config_db() -> Path:
    """The DuckDB config database: in the source tree for a checkout, in the home folder elsewhere."""
    if is_checkout():
        return _ROOT / "deriva" / "adapters" / "database" / "sql.db"
    return home() / "sql.db"


def resolve(value: str | os.PathLike[str]) -> Path:
    """A folder or file from settings: absolute as given, relative against the home folder (never the current folder)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else home() / path
