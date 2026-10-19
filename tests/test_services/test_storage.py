"""What the workspace keeps on disk, and clearing the parts that can go."""

from __future__ import annotations

import pytest

from deriva.services import storage


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path / "workspace" / "graphs"))
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    graphs = tmp_path / "workspace" / "graphs"
    graphs.mkdir(parents=True)
    for key, size in (("alpha", 30), ("gone", 20), ("default", 5)):
        (graphs / f"{key}.grafeo").write_bytes(b"x" * size)
    (graphs / "gone.grafeo.wal").mkdir()
    (graphs / "gone.grafeo.wal" / "0001.log").write_bytes(b"y" * 4)
    cache = tmp_path / "workspace" / "cache" / "llm"
    cache.mkdir(parents=True)
    (cache / "a.json").write_bytes(b"z" * 100)
    (cache / "b.json").write_bytes(b"z" * 50)
    output = tmp_path / "workspace" / "output"
    output.mkdir()
    (output / "deriva-20261019-101010.xml").write_bytes(b"m" * 10)
    (output / "model.xml").write_bytes(b"m" * 10)
    (output / "joint_consistency.json").write_bytes(b"{}")
    sessions = tmp_path / "workspace" / "benchmarks"
    for name in ("bench_1", "bench_2"):
        (sessions / name).mkdir(parents=True)
        (sessions / name / "events.jsonl").write_bytes(b"e" * 7)
    return tmp_path


def test_the_overview_measures_every_area_and_flags_graphs_without_a_repository(home):
    found = storage.overview(repositories={"alpha"}, active="alpha")

    assert found["graphs"] == [
        {"key": "alpha", "bytes": 30, "kind": "repository", "active": True},
        {"key": "gone", "bytes": 24, "kind": "orphaned", "active": False},
        {"key": "default", "bytes": 5, "kind": "shared", "active": False},
    ]
    assert found["llm_cache"] == {"bytes": 150, "files": 2}
    assert found["exports"] == {"bytes": 20, "files": 2}
    assert found["benchmark_sessions"] == {"bytes": 14, "sessions": 2}


def test_clearing_the_llm_cache_empties_it_and_says_how_much_went(home):
    assert storage.clear_llm_cache() == {"bytes": 150, "files": 2}
    assert storage.overview(repositories=set(), active="default")["llm_cache"] == {"bytes": 0, "files": 0}


def test_deleting_exports_removes_the_exchange_files_only(home):
    assert storage.delete_exports() == {"bytes": 20, "files": 2}
    assert sorted(p.name for p in (home / "workspace" / "output").iterdir()) == ["joint_consistency.json"]


def test_an_orphaned_graph_is_deleted_but_never_a_repository_s_or_the_open_one(home):
    assert storage.delete_graph("gone", repositories={"alpha"}, active="alpha") == {"key": "gone", "bytes": 24}
    assert not (home / "workspace" / "graphs" / "gone.grafeo.wal").exists()
    with pytest.raises(ValueError, match="repository"):
        storage.delete_graph("alpha", repositories={"alpha"}, active="default")
    with pytest.raises(ValueError, match="open"):
        storage.delete_graph("default", repositories={"alpha"}, active="default")
    with pytest.raises(KeyError):
        storage.delete_graph("never", repositories={"alpha"}, active="alpha")
