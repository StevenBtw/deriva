"""Translation model packages (Argos Translate, OPUS-MT based), pinned by name, URL and SHA-256.

spaCy language models are ordinary pinned dependencies of this project; the translation
packages are too large for that and are downloaded once into a models directory.
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
    request = urllib.request.Request(url, headers={"User-Agent": "deriva-nlp"})
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
        raise FileNotFoundError(f"Translation model {package.name} is missing in {models_dir}; run `deriva-nlp models` first")
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
