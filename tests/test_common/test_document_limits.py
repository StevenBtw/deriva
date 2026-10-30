"""Hostile documents: a small .docx can unpack to gigabytes, a PDF can hold thousands of pages (decompression bombs)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deriva.common import document_reader


@pytest.fixture
def docx_file(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "notes.docx"
    document = docx.Document()
    document.add_paragraph("Orders are approved by the clerk.")
    document.save(str(path))
    return path


def test_a_normal_docx_is_read(docx_file):
    assert "approved by the clerk" in (document_reader.read_docx(docx_file) or "")


def test_a_docx_that_unpacks_too_large_is_not_read(docx_file, monkeypatch):
    monkeypatch.setattr(document_reader, "MAX_DOCX_UNPACKED", 1000)
    assert document_reader.read_docx(docx_file) is None


def test_a_docx_that_is_no_zip_is_not_read(tmp_path):
    pytest.importorskip("docx")
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    assert document_reader.read_docx(path) is None


def _pdf(pages: list[str]):
    return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda text=text: text) for text in pages])


def test_a_pdf_is_read_up_to_its_page_limit(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(document_reader, "MAX_PDF_PAGES", 2)
    with patch("pypdf.PdfReader", return_value=_pdf(["one", "two", "three"])):
        text = document_reader.read_pdf(tmp_path / "x.pdf") or ""
    assert "one" in text and "two" in text and "three" not in text


def test_a_pdf_stops_at_the_text_limit(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_CHARS", 10)
    with patch("pypdf.PdfReader", return_value=_pdf(["a" * 8, "b" * 8, "c" * 8])):
        text = document_reader.read_pdf(tmp_path / "x.pdf") or ""
    assert "a" * 8 in text and "c" not in text
