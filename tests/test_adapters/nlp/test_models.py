"""Pinned model packages (spaCy pipelines, translation models): downloaded once, verified by SHA-256, unpacked into the models directory."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from deriva.adapters.nlp import models
from deriva.adapters.nlp.models import MtPackage, SpacyPackage, ensure_package, ensure_spacy_package


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

        with pytest.raises(FileNotFoundError, match="is missing"):
            ensure_package(package, tmp_path / "models", download=False)


def test_pinned_packages_cover_german_and_french():
    assert set(models.MT_PACKAGES) == {"de", "fr"}
    assert all(len(p.sha256) == 64 and p.url.startswith("https://") for p in models.MT_PACKAGES.values())


def _fake_wheel(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("xx_test_sm/__init__.py", "")
        wheel.writestr("xx_test_sm/xx_test_sm-1.0.0/config.cfg", "[nlp]\n")
        wheel.writestr("xx_test_sm/xx_test_sm-1.0.0/meta.json", '{"version": "1.0.0"}')
        wheel.writestr("xx_test_sm-1.0.0.dist-info/METADATA", "Name: xx-test-sm\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_pipeline_folder_is_unpacked_from_the_verified_wheel(tmp_path, monkeypatch):
    source = tmp_path / "source.whl"
    digest = _fake_wheel(source)
    monkeypatch.setattr(models, "_download", lambda url, target: Path(target).write_bytes(source.read_bytes()))
    package = SpacyPackage("xx_test_sm", "1.0.0", "https://example.test/xx.whl", digest)

    folder = ensure_spacy_package(package, tmp_path / "models")

    assert folder == tmp_path / "models" / "xx_test_sm-1.0.0"
    assert sorted(p.name for p in folder.iterdir() if not p.name.startswith(".")) == ["config.cfg", "meta.json"]
    assert ensure_spacy_package(package, tmp_path / "models", download=False) == folder  # cached, no download


def test_a_wrong_spacy_checksum_is_refused(tmp_path, monkeypatch):
    source = tmp_path / "source.whl"
    _fake_wheel(source)
    monkeypatch.setattr(models, "_download", lambda url, target: Path(target).write_bytes(source.read_bytes()))

    with pytest.raises(ValueError, match="SHA-256"):
        ensure_spacy_package(SpacyPackage("xx_test_sm", "1.0.0", "https://example.test/xx.whl", "0" * 64), tmp_path / "models")


def test_a_missing_pipeline_without_download_names_the_folder_and_url(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"xx_test_sm-1\.0\.0.*https://example\.test/xx\.whl"):
        ensure_spacy_package(SpacyPackage("xx_test_sm", "1.0.0", "https://example.test/xx.whl", "0" * 64), tmp_path, download=False)


def test_the_spacy_pins_match_the_former_lock():
    assert {lang: (p.name, p.version, p.sha256) for lang, p in models.SPACY_PACKAGES.items()} == {
        "en": ("en_core_web_sm", "3.8.0", "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"),
        "de": ("de_core_news_sm", "3.8.0", "fec69fec52b1780f2d269d5af7582a5e28028738bd3190532459aeb473bfa3e7"),
        "fr": ("fr_core_news_sm", "3.8.0", "7d6ad14cd5078e53147bfbf70fb9d433c6a3865b695fda2657140bbc59a27e29"),
    }
