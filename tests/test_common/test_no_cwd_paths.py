"""No code resolves Deriva state against the current folder or the source tree layout."""

from __future__ import annotations

import re
from pathlib import Path

import deriva

# Every folder of the deriva namespace: the core here, deriva-studio and deriva-dev in packages/
ROOTS = [Path(part).resolve() for part in deriva.__path__]


def _lines():
    for root in ROOTS:
        for file in sorted(root.rglob("*.py")):
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                yield file, number, line


def _relative(file: Path) -> Path:
    return next(file.relative_to(root) for root in ROOTS if file.is_relative_to(root))


READERS = {Path("common/settings.py"), Path("common/paths.py"), Path("services/model_configs.py")}


def test_the_checks_cover_every_package_of_the_namespace():
    """deriva-studio and deriva-dev live in their own folders; the checks read them too."""
    scanned = {file.as_posix() for file, _, _ in _lines()}
    assert any("/deriva/studio/" in f for f in scanned)
    assert any("/deriva/bench/" in f for f in scanned)


def test_configuration_is_read_in_one_place():
    """Only the settings layer reads the environment and .env (paths reads DERIVA_HOME; model_configs edits the file)."""
    pattern = re.compile(r"os\.getenv\(|os\.environ\b|\bload_dotenv\b|\bdotenv_values\b|\bfind_dotenv\b|\benv_file\s*=")
    offenders = [f"{f}:{n}" for f, n, line in _lines() if _relative(f) not in READERS and pattern.search(line)]
    assert offenders == []


def test_nothing_searches_for_a_dotenv_from_the_current_folder():
    offenders = [f"{f}:{n}" for f, n, line in _lines() if "find_dotenv" in line]
    assert offenders == []


def test_no_folder_is_built_from_the_current_folder():
    offenders = [f"{f}:{n}" for f, n, line in _lines() if re.search(r"""Path\(\s*["']\.?/?workspace""", line)]
    assert offenders == []


def test_no_folder_is_built_from_the_source_tree_layout():
    offenders = [f"{f}:{n}" for f, n, line in _lines() if ".parent.parent.parent" in line]
    assert offenders == []
