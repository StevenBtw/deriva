"""Overfit scan of draft prompt texts through the local workspace scanner."""

from __future__ import annotations

from deriva.services.overfit import scan_texts

SCANNER = """
def load_terms():
    return {"widgetco": "repo term", "gadget": "golden Node/r"}


def find(text, terms):
    low = text.lower()
    return sorted(f"'{t}' ({s})" for t, s in terms.items() if t in low)
"""


def test_findings_are_reported_per_field(tmp_path):
    scanner = tmp_path / "scanner.py"
    scanner.write_text(SCANNER, encoding="utf-8")

    result = scan_texts({"instruction": "Name it like WidgetCo", "example": "plain", "params": '{"note": "a gadget"}'}, scanner=scanner)

    assert result == {
        "available": True,
        "findings": [{"field": "instruction", "finding": "'widgetco' (repo term)"}, {"field": "params", "finding": "'gadget' (golden Node/r)"}],
    }


def test_without_the_local_scanner_the_scan_is_unavailable(tmp_path):
    assert scan_texts({"instruction": "x"}, scanner=tmp_path / "missing.py") == {"available": False, "findings": []}
