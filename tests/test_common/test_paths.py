"""The home folder: DERIVA_HOME, else the checkout root, else ~/.deriva."""

from __future__ import annotations

from pathlib import Path

from deriva.common import paths

REPO_ROOT = Path(paths.__file__).resolve().parents[2]


def test_a_checkout_is_its_own_home(monkeypatch):
    monkeypatch.delenv("DERIVA_HOME", raising=False)

    assert paths.is_checkout()
    assert paths.home() == REPO_ROOT
    assert paths.env_file() == REPO_ROOT / ".env"
    assert paths.workspace() == REPO_ROOT / "workspace"
    assert paths.config_db() == REPO_ROOT / "deriva" / "adapters" / "database" / "sql.db"


def test_deriva_home_wins_and_holds_the_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))

    assert not paths.is_checkout()
    assert paths.home() == tmp_path.resolve()
    assert paths.env_file() == tmp_path.resolve() / ".env"
    assert paths.workspace() == tmp_path.resolve() / "workspace"
    assert paths.config_db() == tmp_path.resolve() / "sql.db"


def test_an_installed_tool_lives_in_dot_deriva(monkeypatch, tmp_path):
    monkeypatch.delenv("DERIVA_HOME", raising=False)
    monkeypatch.setattr(paths, "_ROOT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))

    assert not paths.is_checkout()
    assert paths.home() == tmp_path / "user" / ".deriva"
    assert paths.config_db() == tmp_path / "user" / ".deriva" / "sql.db"


def test_relative_settings_resolve_against_home_not_the_current_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("DERIVA_HOME", str(tmp_path / "home"))
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    assert paths.resolve("workspace/graphs") == (tmp_path / "home").resolve() / "workspace" / "graphs"
    assert paths.resolve(tmp_path / "abs") == tmp_path / "abs"


def test_deriva_home_may_be_relative_tilde_or_empty(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DERIVA_HOME", "rel-home")
    assert paths.home() == (tmp_path / "rel-home").resolve()

    monkeypatch.setenv("DERIVA_HOME", "~/deriva-home")
    assert paths.home() == (Path.home() / "deriva-home").resolve()

    monkeypatch.setenv("DERIVA_HOME", "  ")
    assert paths.home() == REPO_ROOT
