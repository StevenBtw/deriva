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
    return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda text=text: text, get_contents=lambda: None) for text in pages])


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
    assert "a" * 8 in text and "b" not in text and "c" not in text


def test_a_pdf_stops_at_the_unpacked_limit_and_says_so(tmp_path, monkeypatch, caplog):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(document_reader, "MAX_PDF_UNPACKED", 10)
    extracted = []

    def page(text):
        stream = SimpleNamespace(get_data=lambda: b"x" * 8)
        return SimpleNamespace(extract_text=lambda: extracted.append(text) or text, get_contents=lambda: stream)

    with patch("pypdf.PdfReader", return_value=SimpleNamespace(pages=[page("one"), page("two"), page("three")])), caplog.at_level("WARNING"):
        text = document_reader.read_pdf(tmp_path / "x.pdf") or ""
    assert "one" in text and "two" not in text
    assert extracted == ["one"]  # Nothing past the limit is parsed
    assert "read up to page 1" in caplog.text


def test_a_docx_over_the_limit_says_why(docx_file, monkeypatch, caplog):
    monkeypatch.setattr(document_reader, "MAX_DOCX_UNPACKED", 1000)
    with caplog.at_level("WARNING"):
        assert document_reader.read_docx(docx_file) is None
    assert "unpacks to more than 1000 bytes" in caplog.text


def test_a_page_past_the_text_limit_is_not_unpacked(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_CHARS", 8)

    def broken():
        raise ValueError("bad stream")

    pages = [SimpleNamespace(extract_text=lambda: "a" * 8, get_contents=lambda: None), SimpleNamespace(extract_text=lambda: "b", get_contents=broken)]
    with patch("pypdf.PdfReader", return_value=SimpleNamespace(pages=pages)):
        text = document_reader.read_pdf(tmp_path / "x.pdf")
    assert text is not None and "a" * 8 in text  # The read pages stay
