"""Translation model packages: downloaded once, verified by SHA-256, unpacked into the models directory."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from deriva_nlp import models
from deriva_nlp.models import MtPackage, ensure_package


def _fake_package(tmp_path: Path, name: str) -> tuple[Path, str]:
    archive = tmp_path / f"{name}.argosmodel"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"{name}/model/model.bin", b"weights")
        z.writestr(f"{name}/sentencepiece.model", b"pieces")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


class TestEnsurePackage:
    def test_downloads_verifies_and_unpacks(self, tmp_path, monkeypatch):
        archive, digest = _fake_package(tmp_path, "translate-xx_en-1_0")
        monkeypatch.setattr(models, "_download", lambda url, target: target.write_bytes(archive.read_bytes()))
        package = MtPackage(name="translate-xx_en-1_0", url="https://example.invalid/x", sha256=digest)

        path = ensure_package(package, tmp_path / "models")

        assert (path / "sentencepiece.model").read_bytes() == b"pieces"
        assert (path / "model" / "model.bin").exists()

    def test_a_wrong_hash_is_refused_and_nothing_is_unpacked(self, tmp_path, monkeypatch):
        archive, _ = _fake_package(tmp_path, "translate-xx_en-1_0")
        monkeypatch.setattr(models, "_download", lambda url, target: target.write_bytes(archive.read_bytes()))
        package = MtPackage(name="translate-xx_en-1_0", url="https://example.invalid/x", sha256="0" * 64)

        with pytest.raises(ValueError, match="SHA-256"):
            ensure_package(package, tmp_path / "models")
        assert not (tmp_path / "models" / "translate-xx_en-1_0").exists()

    def test_an_unpacked_package_is_not_downloaded_again(self, tmp_path, monkeypatch):
        archive, digest = _fake_package(tmp_path, "translate-xx_en-1_0")
        calls = []
        monkeypatch.setattr(models, "_download", lambda url, target: (calls.append(url), target.write_bytes(archive.read_bytes())))
        package = MtPackage(name="translate-xx_en-1_0", url="https://example.invalid/x", sha256=digest)

        ensure_package(package, tmp_path / "models")
        ensure_package(package, tmp_path / "models")

        assert len(calls) == 1

    def test_no_download_allowed_raises_when_missing(self, tmp_path):
        package = MtPackage(name="translate-xx_en-1_0", url="https://example.invalid/x", sha256="0" * 64)

        with pytest.raises(FileNotFoundError, match="deriva-nlp models"):
            ensure_package(package, tmp_path / "models", download=False)


def test_pinned_packages_cover_german_and_french():
    assert set(models.MT_PACKAGES) == {"de", "fr"}
    assert all(len(p.sha256) == 64 and p.url.startswith("https://") for p in models.MT_PACKAGES.values())
