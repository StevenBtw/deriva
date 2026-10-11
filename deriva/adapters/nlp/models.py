"""Pinned model packages, downloaded once into the models directory and verified by SHA-256.

The spaCy pipelines (wheels from their GitHub releases) and the translation packages
(Argos Translate, OPUS-MT based), each by name, URL and SHA-256.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MtPackage:
    name: str
    url: str
    sha256: str


# Source language -> English
MT_PACKAGES = {
    "de": MtPackage(
        name="translate-de_en-1_3",
        url="https://argos-net.com/v1/translate-de_en-1_3.argosmodel",
        sha256="becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637",
    ),
    "fr": MtPackage(
        name="translate-fr_en-1_9",
        url="https://argos-net.com/v1/translate-fr_en-1_9.argosmodel",
        sha256="3b3052fee6bb1e8e8e632a26a723eb2a2c7710dfe73ba61ffd9b83e85d4f14c1",
    ),
}


def _download(url: str, target: Path) -> None:
    # The package host refuses requests without a user agent
    request = urllib.request.Request(url, headers={"User-Agent": "deriva"})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as out:  # noqa: S310 - pinned https URL
        shutil.copyfileobj(response, out)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_package(package: MtPackage, models_dir: Path, download: bool = True) -> Path:
    """The unpacked package directory; downloads and verifies it first when it is missing.

    A verified package leaves a marker holding its SHA-256, so a directory from another
    version is never mistaken for this one.
    """
    target = models_dir / package.name
    marker = target / ".sha256"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == package.sha256:
        return target
    if not download:
        raise FileNotFoundError(f"Translation model {package.name} is missing in {models_dir}; the business concept step downloads it")
    models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=models_dir) as tmp:
        archive = Path(tmp) / f"{package.name}.argosmodel"
        _download(package.url, archive)
        digest = _sha256(archive)
        if digest != package.sha256:
            raise ValueError(f"SHA-256 of {package.name} is {digest}, expected {package.sha256}")
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(Path(tmp) / package.name), str(target))
    marker.write_text(package.sha256, encoding="utf-8")
    return target


def ensure_all(models_dir: Path, download: bool = True) -> dict[str, Path]:
    """Every pinned translation package, by source language."""
    return {lang: ensure_package(package, models_dir, download) for lang, package in sorted(MT_PACKAGES.items())}


@dataclass(frozen=True)
class SpacyPackage:
    name: str
    version: str
    url: str
    sha256: str

    @property
    def folder(self) -> str:
        return f"{self.name}-{self.version}"


_SPACY_RELEASES = "https://github.com/explosion/spacy-models/releases/download"
# The pipelines that decide the output; the hashes are the ones the dependency lock recorded
SPACY_PACKAGES = {
    "en": SpacyPackage(
        name="en_core_web_sm",
        version="3.8.0",
        url=f"{_SPACY_RELEASES}/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
        sha256="1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85",
    ),
    "de": SpacyPackage(
        name="de_core_news_sm",
        version="3.8.0",
        url=f"{_SPACY_RELEASES}/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl",
        sha256="fec69fec52b1780f2d269d5af7582a5e28028738bd3190532459aeb473bfa3e7",
    ),
    "fr": SpacyPackage(
        name="fr_core_news_sm",
        version="3.8.0",
        url=f"{_SPACY_RELEASES}/fr_core_news_sm-3.8.0/fr_core_news_sm-3.8.0-py3-none-any.whl",
        sha256="7d6ad14cd5078e53147bfbf70fb9d433c6a3865b695fda2657140bbc59a27e29",
    ),
}


def ensure_spacy_package(package: SpacyPackage, models_dir: Path, download: bool = True) -> Path:
    """The unpacked pipeline folder ``<models_dir>/<name>-<version>``; downloads and verifies the wheel first when it is missing."""
    target = models_dir / package.folder
    marker = target / ".sha256"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == package.sha256:
        return target
    if not download:
        raise FileNotFoundError(f"spaCy pipeline {package.folder} is missing in {models_dir}; the business concept step downloads it from {package.url}")
    models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=models_dir) as work:
        wheel = Path(work) / f"{package.folder}.whl"
        _download(package.url, wheel)
        digest = _sha256(wheel)
        if digest != package.sha256:
            raise ValueError(f"SHA-256 of {package.folder} is {digest}, expected {package.sha256}")
        prefix = f"{package.name}/{package.folder}/"
        staging = Path(work) / "pipeline"
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.namelist():
                if member.startswith(prefix) and not member.endswith("/") and ".." not in member:
                    out = staging / member[len(prefix) :]
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(archive.read(member))
        # The checksum is part of the folder that is moved into place: a folder that is there is complete
        (staging / ".sha256").write_text(package.sha256, encoding="utf-8")
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(staging), str(target))
        except OSError, shutil.Error:
            # Another first-time caller installed the same verified pipeline in between
            if not (marker.exists() and marker.read_text(encoding="utf-8").strip() == package.sha256):
                raise
    return target


def ensure_spacy(models_dir: Path, download: bool = True) -> dict[str, Path]:
    """The pinned spaCy pipelines per language, downloaded once into the models directory."""
    return {lang: ensure_spacy_package(package, models_dir, download) for lang, package in sorted(SPACY_PACKAGES.items())}
