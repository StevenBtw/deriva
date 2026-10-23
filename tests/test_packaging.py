"""The packages hold exactly their module trees: tracked files, the studio's built front end, nothing local."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_JUNK = (".mypy_cache/", ".ruff_cache/", "__pycache__/", "sql.db")


@pytest.fixture(scope="module")
def built_dist(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--all-packages", "--no-sources", "--wheel", "-o", str(out)], cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def built_wheels(built_dist) -> dict[str, set[str]]:
    return {wheel.name.split("-")[0]: set(zipfile.ZipFile(wheel).namelist()) for wheel in built_dist.glob("*.whl")}


@pytest.mark.parametrize("package", ["deriva_cli", "deriva_studio", "deriva_dev"])
def test_every_wheel_carries_the_license_text(built_dist, package):
    """AGPL: each package ships the license text itself, identical to the repository's LICENSE."""
    with zipfile.ZipFile(next(built_dist.glob(f"{package}-*.whl"))) as wheel:
        licenses = [m for m in wheel.namelist() if ".dist-info/licenses/" in m and m.endswith("LICENSE")]
        assert len(licenses) == 1
        assert wheel.read(licenses[0]) == (ROOT / "LICENSE").read_bytes()


@pytest.mark.parametrize("package", ["deriva_cli", "deriva_studio", "deriva_dev"])
def test_no_runtime_requirement_needs_a_pre_release(built_dist, package):
    """uv takes a pre-release only for a requirement the user names: a dependency on one (grafeo>=0.6.0b1) made
    `uv tool install deriva-studio` fall back to the empty 0.0.1 placeholder. Every Requires-Dist names a final release."""
    from packaging.requirements import Requirement
    from packaging.version import Version

    with zipfile.ZipFile(next(built_dist.glob(f"{package}-*.whl"))) as wheel:
        metadata = wheel.read(next(m for m in wheel.namelist() if m.endswith(".dist-info/METADATA"))).decode("utf-8")
    requirements = [Requirement(line.split(":", 1)[1].strip()) for line in metadata.splitlines() if line.startswith("Requires-Dist:")]
    assert requirements, "the wheel lists its requirements"
    pre_releases = [str(r) for r in requirements for spec in r.specifier if Version(spec.version).is_prerelease]
    assert pre_releases == []


def _tracked(prefix: str) -> set[str]:
    """Source files of the working tree under ``prefix``: tracked or new, not ignored, still present (renames and new files count)."""
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", prefix], cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
    files = {f for f in listed if (ROOT / f).is_file()}
    # ruff.toml files are lint configuration of the source tree, not package content
    return {f for f in files if (f.endswith(".py") or "/data/" in f or f.endswith((".sql", ".yaml", ".xsd", ".json", ".toml", ".md"))) and not f.endswith("ruff.toml")}


def test_deriva_cli_holds_the_core_and_nothing_local(built_wheels):
    members = {m for m in built_wheels["deriva_cli"] if not m.startswith("deriva_cli-")}
    assert not [m for m in members if any(junk in m for junk in LOCAL_JUNK)]
    assert not [m for m in members if m.startswith(("deriva/studio/", "deriva/bench/"))]
    assert "deriva/__init__.py" not in members
    assert {f for f in _tracked("deriva") if not f.startswith(("deriva/studio/", "deriva/bench/")) and f != "deriva/__init__.py"} <= members


def test_deriva_dev_holds_only_the_bench_package(built_wheels):
    members = {m for m in built_wheels["deriva_dev"] if not m.startswith("deriva_dev-") and not m.endswith("/")}
    assert members and all(m.startswith("deriva/bench/") for m in members)
    assert not [m for m in members if any(junk in m for junk in LOCAL_JUNK)]


def test_deriva_studio_holds_the_studio_and_its_front_end(built_wheels):
    members = {m for m in built_wheels["deriva_studio"] if not m.startswith("deriva_studio-") and not m.endswith("/")}
    assert members and all(m.startswith("deriva/studio/") for m in members)
    # The front end is built before packaging and is not in the repository: a checkout that has it ships it
    # (the package build in CI builds it first and checks the wheel for it)
    if (ROOT / "packages/deriva-studio/src/deriva/studio/static/index.html").is_file():
        assert "deriva/studio/static/index.html" in members
    assert not [m for m in members if any(junk in m for junk in LOCAL_JUNK)]
