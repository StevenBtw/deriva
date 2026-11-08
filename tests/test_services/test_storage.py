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
    assert found["llm_cache"] == {"bytes": 150, "files": 2, "entries": None}
    assert found["exports"] == {"bytes": 20, "files": 2}
    assert found["benchmark_sessions"] == {"bytes": 14, "sessions": 2}


def test_clearing_the_llm_cache_empties_it_and_says_how_much_went(home):
    assert storage.clear_llm_cache() == {"bytes": 150, "files": 2, "entries": None}
    assert storage.overview(repositories=set(), active="default")["llm_cache"] == {"bytes": 0, "files": 0, "entries": None}


def test_an_lmdb_cache_is_measured_by_what_it_holds_not_by_its_map_file(tmp_path, monkeypatch):
    """lmdb's data.mdb is as large as its map (sparse on disk): the overview counts the cached answers and their bytes."""
    from deriva.common.cache_utils import BaseDiskCache

    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    folder = storage.llm_cache_folder()
    cache = BaseDiskCache(folder)
    for n in range(3):
        cache.set(f"key{n}", {"content": "x" * 100})
    cache.close()
    map_file = (folder / "data.mdb").stat().st_size

    found = storage.overview(repositories=set(), active="default")["llm_cache"]

    assert found["entries"] == 3 and found["files"] == 2
    assert 300 < found["bytes"] < 2000 < map_file
    assert storage.clear_llm_cache() == found
    assert storage.overview(repositories=set(), active="default")["llm_cache"] == {"bytes": 0, "files": 0, "entries": None}


def test_a_map_file_lmdb_cannot_read_is_measured_by_its_files_and_left_as_it_was(tmp_path, monkeypatch):
    """A data.mdb that is no lmdb map (damaged, another format) does not break the overview: the files are measured,
    the answers are unknown, and the failed open leaves the file's bytes alone."""
    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    folder = storage.llm_cache_folder()
    folder.mkdir(parents=True)
    junk = b"not an lmdb map" * 3
    (folder / "data.mdb").write_bytes(junk)

    found = storage.overview(repositories=set(), active="default")["llm_cache"]

    assert found == {"bytes": len(junk), "files": 1, "entries": None}
    assert (folder / "data.mdb").read_bytes() == junk


def _files_measure(folder):
    files = [p for p in folder.iterdir() if p.is_file()]
    return {"bytes": sum(p.stat().st_size for p in files), "files": len(files), "entries": None}


def test_a_cache_whose_state_is_not_deriva_s_is_measured_by_its_files(tmp_path, monkeypatch):
    """A meta state that is JSON but no dict with a size ("[]") gives no answer count; the overview does not fail."""
    import lmdb

    from deriva.common.cache_utils import BaseDiskCache

    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    folder = storage.llm_cache_folder()
    cache = BaseDiskCache(folder)
    cache.set("key", {"content": "x"})
    cache.close()
    env = lmdb.open(str(folder), max_dbs=2)
    with env.begin(write=True) as txn:
        txn.put(b"state", b"[]", db=env.open_db(b"meta", txn=txn))
    env.close()

    assert storage.overview(repositories=set(), active="default")["llm_cache"] == _files_measure(folder)


def test_measuring_an_lmdb_map_that_is_not_deriva_s_writes_nothing_to_it(tmp_path, monkeypatch):
    """A valid lmdb map with databases of its own is no Deriva cache: it is measured by its files, and measuring
    opens it read-only, so it does not gain Deriva's entries and meta databases."""
    import lmdb

    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    folder = storage.llm_cache_folder()
    folder.mkdir(parents=True)
    env = lmdb.open(str(folder), max_dbs=2)
    with env.begin(write=True) as txn:
        txn.put(b"k", b"v", db=env.open_db(b"other", txn=txn))
    env.close()

    assert storage.overview(repositories=set(), active="default")["llm_cache"] == _files_measure(folder)

    env = lmdb.open(str(folder), readonly=True, max_dbs=2)
    with env.begin() as txn:
        main = [key for key, _ in txn.cursor()]
    env.close()
    assert main == [b"other"]


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
